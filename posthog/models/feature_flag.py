import hashlib
from typing import Any, Dict, List, Optional, Union, cast

from django.contrib.auth.models import AnonymousUser
from django.db import models
from django.db.models.expressions import ExpressionWrapper, RawSQL, Subquery
from django.db.models.fields import BooleanField
from django.db.models.query import QuerySet
from django.utils import timezone
from sentry_sdk.api import capture_exception

from posthog.models.filters.mixins.utils import cached_property
from posthog.models.team import Team
from posthog.models.user import User
from posthog.queries.base import properties_to_Q

from .filters import Filter
from .person import Person, PersonDistinctId

__LONG_SCALE__ = float(0xFFFFFFFFFFFFFFF)


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

    def distinct_id_matches(self, distinct_id: str) -> bool:
        return FeatureFlagMatcher(distinct_id, self).is_match()

    def get_variant_for_distinct_id(self, distinct_id: str) -> Optional[str]:
        return FeatureFlagMatcher(distinct_id, self).get_matching_variant()

    def get_analytics_metadata(self) -> Dict:
        filter_count = sum(len(group.get("properties", [])) for group in self.groups)
        variants_count = len(self.variants)

        return {
            "groups_count": len(self.groups),
            "has_variants": variants_count > 0,
            "variants_count": variants_count,
            "has_filters": filter_count > 0,
            "has_rollout_percentage": any(group.get("rollout_percentage") for group in self.groups),
            "filter_count": filter_count,
            "created_at": self.created_at,
        }

    @property
    def groups(self):
        return self.get_filters().get("groups", []) or []

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


class FeatureFlagMatcher:
    def __init__(self, distinct_id: str, feature_flag: FeatureFlag):
        self.distinct_id = distinct_id
        self.feature_flag = feature_flag

    def is_match(self):
        return any(self.is_group_match(group, index) for index, group in enumerate(self.feature_flag.groups))

    def get_matching_variant(self) -> Optional[str]:
        for variant in self.variant_lookup_table:
            if self._variant_hash >= variant["value_min"] and self._variant_hash < variant["value_max"]:
                return variant["key"]
        return None

    def is_group_match(self, group: Dict, group_index: int):
        rollout_percentage = group.get("rollout_percentage")
        if len(group.get("properties", [])) > 0:
            if not self._match_distinct_id(group_index):
                return False
            elif not rollout_percentage:
                return True

        if rollout_percentage is not None and self._hash > (rollout_percentage / 100):
            return False

        return True

    def _match_distinct_id(self, group_index: int) -> bool:
        return len(self.query_groups) > 0 and self.query_groups[0][group_index]

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
    def query_groups(self) -> List[List[bool]]:
        query: QuerySet = Person.objects.filter(
            team_id=self.feature_flag.team_id,
            persondistinctid__distinct_id=self.distinct_id,
            persondistinctid__team_id=self.feature_flag.team_id,
        )

        fields = []
        for index, group in enumerate(self.feature_flag.groups):
            key = f"group_{index}"

            if len(group.get("properties", {})) > 0:
                expr: Any = properties_to_Q(
                    Filter(data=group).properties, team_id=self.feature_flag.team_id, is_person_query=True
                )
            else:
                expr = RawSQL("true", [])

            query = query.annotate(**{key: ExpressionWrapper(expr, output_field=BooleanField())})
            fields.append(key)

        return list(query.values_list(*fields))

    # This function takes a distinct_id and a feature flag key and returns a float between 0 and 1.
    # Given the same distinct_id and key, it'll always return the same float. These floats are
    # uniformly distributed between 0 and 1, so if we want to show this feature to 20% of traffic
    # we can do _hash(key, distinct_id) < 0.2
    def get_hash(self, salt="") -> float:
        hash_key = "%s.%s%s" % (self.feature_flag.key, self.distinct_id, salt)
        hash_val = int(hashlib.sha1(hash_key.encode("utf-8")).hexdigest()[:15], 16)
        return hash_val / __LONG_SCALE__

    @cached_property
    def _hash(self):
        return self.get_hash()

    @cached_property
    def _variant_hash(self) -> float:
        return self.get_hash(salt="variant")


# Return a Dict with all active flags and their values
def get_active_feature_flags(team: Team, distinct_id: str) -> Dict[str, Union[bool, str, None]]:
    flags_enabled: Dict[str, Union[bool, str, None]] = {}
    feature_flags = FeatureFlag.objects.filter(team=team, active=True, deleted=False).only(
        "id", "team_id", "filters", "key", "rollout_percentage",
    )

    for feature_flag in feature_flags:
        try:
            if not feature_flag.distinct_id_matches(distinct_id):
                continue
            if len(feature_flag.variants) > 0:
                variant = feature_flag.get_variant_for_distinct_id(distinct_id)
                if variant is not None:
                    flags_enabled[feature_flag.key] = variant
            else:
                flags_enabled[feature_flag.key] = True
        except Exception as err:
            capture_exception(err)
    return flags_enabled


# Return feature flags with per-user overrides
def get_overridden_feature_flags(team: Team, distinct_id: str,) -> Dict[str, Union[bool, str, None]]:
    feature_flags = get_active_feature_flags(team, distinct_id)

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
        if value is False:
            if key in feature_flags:
                del feature_flags[key]
        else:
            feature_flags[key] = value

    return feature_flags
