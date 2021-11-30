import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from django.contrib.auth.models import AnonymousUser
from django.db import models
from django.db.models.expressions import ExpressionWrapper, RawSQL, Subquery
from django.db.models.fields import BooleanField
from django.db.models.query import QuerySet
from django.utils import timezone
from sentry_sdk.api import capture_exception

from posthog.models.filters.mixins.utils import cached_property
from posthog.models.group import Group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.property import GroupTypeIndex, GroupTypeName
from posthog.models.team import Team
from posthog.models.user import User
from posthog.queries.base import properties_to_Q

from .filters import Filter
from .person import Person, PersonDistinctId

__LONG_SCALE__ = float(0xFFFFFFFFFFFFFFF)


@dataclass
class FeatureFlagMatch:
    variant: Optional[str] = None


class FeatureFlag(models.Model):
    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "key"], name="unique key for team")]

    key: models.CharField = models.CharField(max_length=400)
    name: models.TextField = models.TextField(
        blank=True,
    )  # contains description for the FF (field name `name` is kept for backwards-compatibility)

    filters: models.JSONField = models.JSONField(default=dict)
    rollout_percentage: models.IntegerField = models.IntegerField(null=True, blank=True)

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    deleted: models.BooleanField = models.BooleanField(default=False)
    active: models.BooleanField = models.BooleanField(default=True)

    def matches(self, *args, **kwargs) -> Optional[FeatureFlagMatch]:
        return FeatureFlagMatcher(self, *args, **kwargs).get_match()

    def get_analytics_metadata(self) -> Dict:
        filter_count = sum(len(condition.get("properties", [])) for condition in self.conditions)
        variants_count = len(self.variants)

        return {
            "groups_count": len(self.conditions),
            "has_variants": variants_count > 0,
            "variants_count": variants_count,
            "has_filters": filter_count > 0,
            "has_rollout_percentage": any(condition.get("rollout_percentage") for condition in self.conditions),
            "filter_count": filter_count,
            "created_at": self.created_at,
            "aggregating_by_groups": self.aggregation_group_type_index is not None,
        }

    @property
    def conditions(self):
        "Each feature flag can have multiple conditions to match, they are OR-ed together."
        return self.get_filters().get("groups", []) or []

    @property
    def aggregation_group_type_index(self) -> Optional[GroupTypeIndex]:
        "If None, aggregating this feature flag by persons, otherwise by groups of given group_type_index"
        return self.get_filters().get("aggregation_group_type_index", None)

    @property
    def variants(self):
        # :TRICKY: .get("multivariate", {}) returns "None" if the key is explicitly set to "null" inside json filters
        multivariate = self.get_filters().get("multivariate", None)
        if isinstance(multivariate, dict):
            variants = multivariate.get("variants", None)
            if isinstance(variants, list):
                return variants
        return []

    def get_filters(self):
        if "groups" in self.filters:
            return self.filters
        else:
            # :TRICKY: Keep this backwards compatible.
            #   We don't want to migrate to avoid /decide endpoint downtime until this code has been deployed
            return {
                "groups": [
                    {"properties": self.filters.get("properties", []), "rollout_percentage": self.rollout_percentage}
                ]
            }


class FeatureFlagOverride(models.Model):
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "feature_flag", "team"], name="unique feature flag for a user/team combo"
            )
        ]

    feature_flag: models.ForeignKey = models.ForeignKey("FeatureFlag", on_delete=models.CASCADE)
    user: models.ForeignKey = models.ForeignKey("User", on_delete=models.CASCADE)
    override_value: models.JSONField = models.JSONField()
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)

    def get_analytics_metadata(self) -> Dict:
        return {
            "override_value_type": type(self.override_value).__name__,
        }


class FlagsMatcherCache:
    def __init__(self, team_id: int):
        self.team_id = team_id

    @cached_property
    def group_types_to_indexes(self) -> Dict[GroupTypeName, GroupTypeIndex]:
        group_type_mapping_rows = GroupTypeMapping.objects.filter(team_id=self.team_id)
        return {row.group_type: row.group_type_index for row in group_type_mapping_rows}

    @cached_property
    def group_type_index_to_name(self) -> Dict[GroupTypeIndex, GroupTypeName]:
        return {value: key for key, value in self.group_types_to_indexes.items()}


class FeatureFlagMatcher:
    def __init__(
        self,
        feature_flag: FeatureFlag,
        distinct_id: str,
        groups: Dict[GroupTypeName, str] = {},
        cache: Optional[FlagsMatcherCache] = None,
    ):
        self.feature_flag = feature_flag
        self.distinct_id = distinct_id
        self.groups = groups
        self.cache = cache or FlagsMatcherCache(self.feature_flag.team_id)

    def get_match(self) -> Optional[FeatureFlagMatch]:
        # If aggregating flag by groups and relevant group type is not passed - flag is off!
        if self.hashed_identifier is None:
            return None

        is_match = any(
            self.is_condition_match(condition, index) for index, condition in enumerate(self.feature_flag.conditions)
        )
        if is_match:
            return FeatureFlagMatch(variant=self.get_matching_variant())
        else:
            return None

    def get_matching_variant(self) -> Optional[str]:
        for variant in self.variant_lookup_table:
            if self._variant_hash >= variant["value_min"] and self._variant_hash < variant["value_max"]:
                return variant["key"]
        return None

    def is_condition_match(self, condition: Dict, condition_index: int):
        rollout_percentage = condition.get("rollout_percentage")
        if len(condition.get("properties", [])) > 0:
            if not self._condition_matches(condition_index):
                return False
            elif rollout_percentage is None:
                return True

        if rollout_percentage is not None and self._hash > (rollout_percentage / 100):
            return False

        return True

    def _condition_matches(self, condition_index: int) -> bool:
        return len(self.query_conditions) > 0 and self.query_conditions[0][condition_index]

    # Define contiguous sub-domains within [0, 1].
    # By looking up a random hash value, you can find the associated variant key.
    # e.g. the first of two variants with 50% rollout percentage will have value_max: 0.5
    # and the second will have value_min: 0.5 and value_max: 1.0
    @property
    def variant_lookup_table(self):
        lookup_table = []
        value_min = 0
        for variant in self.feature_flag.variants:
            value_max = value_min + variant["rollout_percentage"] / 100
            lookup_table.append({"value_min": value_min, "value_max": value_max, "key": variant["key"]})
            value_min = value_max
        return lookup_table

    @cached_property
    def query_conditions(self) -> List[List[bool]]:
        if self.feature_flag.aggregation_group_type_index is None:
            query: QuerySet = Person.objects.filter(
                team_id=self.feature_flag.team_id,
                persondistinctid__distinct_id=self.distinct_id,
                persondistinctid__team_id=self.feature_flag.team_id,
            )
        else:
            query = Group.objects.filter(
                team_id=self.feature_flag.team_id,
                group_type_index=self.feature_flag.aggregation_group_type_index,
                group_key=self.hashed_identifier,
            )

        fields = []
        for index, condition in enumerate(self.feature_flag.conditions):
            key = f"condition_{index}"

            if len(condition.get("properties", {})) > 0:
                expr: Any = properties_to_Q(
                    Filter(data=condition).properties, team_id=self.feature_flag.team_id, is_direct_query=True
                )
            else:
                expr = RawSQL("true", [])

            query = query.annotate(**{key: ExpressionWrapper(expr, output_field=BooleanField())})
            fields.append(key)

        return list(query.values_list(*fields))

    @property
    def hashed_identifier(self) -> Optional[str]:
        """
        If aggregating by people, returns distinct_id.

        Otherwise, returns the relevant group_key.

        If relevant group is not passed to the flag, None is returned and handled in get_match.
        """
        if self.feature_flag.aggregation_group_type_index is None:
            return self.distinct_id
        else:
            # :TRICKY: If aggregating by groups
            group_type_name = self.cache.group_type_index_to_name.get(self.feature_flag.aggregation_group_type_index)
            group_key = self.groups.get(group_type_name)  # type: ignore
            return group_key

    # This function takes a identifier and a feature flag key and returns a float between 0 and 1.
    # Given the same identifier and key, it'll always return the same float. These floats are
    # uniformly distributed between 0 and 1, so if we want to show this feature to 20% of traffic
    # we can do _hash(key, identifier) < 0.2
    def get_hash(self, salt="") -> float:
        hash_key = f"{self.feature_flag.key}.{self.hashed_identifier}{salt}"
        hash_val = int(hashlib.sha1(hash_key.encode("utf-8")).hexdigest()[:15], 16)
        return hash_val / __LONG_SCALE__

    @cached_property
    def _hash(self):
        return self.get_hash()

    @cached_property
    def _variant_hash(self) -> float:
        return self.get_hash(salt="variant")


# Return a Dict with all active flags and their values
def get_active_feature_flags(
    team: Team, distinct_id: str, groups: Dict[GroupTypeName, str] = {}
) -> Dict[str, Union[bool, str, None]]:
    cache = FlagsMatcherCache(team.pk)
    flags_enabled: Dict[str, Union[bool, str, None]] = {}
    feature_flags = FeatureFlag.objects.filter(team=team, active=True, deleted=False).only(
        "id", "team_id", "filters", "key", "rollout_percentage",
    )

    for feature_flag in feature_flags:
        try:
            match = feature_flag.matches(distinct_id, groups, cache)
            if match:
                flags_enabled[feature_flag.key] = match.variant or True
        except Exception as err:
            capture_exception(err)
    return flags_enabled


# Return feature flags with per-user overrides
def get_overridden_feature_flags(
    team: Team, distinct_id: str, groups: Dict[GroupTypeName, str] = {}
) -> Dict[str, Union[bool, str, None]]:
    feature_flags = get_active_feature_flags(team, distinct_id, groups)

    # Get a user's feature flag overrides from any distinct_id (not just the canonical one)
    person = PersonDistinctId.objects.filter(distinct_id=distinct_id, team=team).values_list("person_id")[:1]
    distinct_ids = PersonDistinctId.objects.filter(person_id__in=Subquery(person)).values_list("distinct_id")
    user_id = User.objects.filter(distinct_id__in=Subquery(distinct_ids))[:1].values_list("id")
    feature_flag_overrides = FeatureFlagOverride.objects.filter(
        user_id__in=Subquery(user_id), team=team
    ).select_related("feature_flag")
    feature_flag_overrides = feature_flag_overrides.only("override_value", "feature_flag__key")

    for feature_flag_override in feature_flag_overrides:
        key = feature_flag_override.feature_flag.key
        value = feature_flag_override.override_value
        if value is False and key in feature_flags:
            del feature_flags[key]
        else:
            feature_flags[key] = value

    return feature_flags
