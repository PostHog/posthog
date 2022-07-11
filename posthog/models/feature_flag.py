import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from django.core.cache import cache
from django.db import models
from django.db.models.expressions import ExpressionWrapper, RawSQL
from django.db.models.fields import BooleanField
from django.db.models.query import QuerySet
from django.db.models.signals import pre_delete
from django.utils import timezone
from sentry_sdk.api import capture_exception

from posthog.models.cohort import Cohort
from posthog.models.experiment import Experiment
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.group import Group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.property import GroupTypeIndex, GroupTypeName
from posthog.models.signals import mutable_receiver
from posthog.queries.base import properties_to_Q

from .filters import Filter
from .person import Person, PersonDistinctId

__LONG_SCALE__ = float(0xFFFFFFFFFFFFFFF)


@dataclass(frozen=True)
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

    ensure_experience_continuity: models.BooleanField = models.BooleanField(default=False, null=True, blank=True)

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
                    {"properties": self.filters.get("properties", []), "rollout_percentage": self.rollout_percentage},
                ],
            }

    @property
    def cohort_ids(self) -> List[int]:
        cohort_ids = []
        for condition in self.conditions:
            props = condition.get("properties", [])
            for prop in props:
                if prop.get("type", None) == "cohort":
                    cohort_id = prop.get("value", None)
                    if cohort_id:
                        cohort_ids.append(cohort_id)
        return cohort_ids

    def update_cohorts(self) -> None:
        from posthog.tasks.calculate_cohort import update_cohort
        from posthog.tasks.cohorts_in_feature_flag import COHORT_ID_IN_FF_KEY

        if self.cohort_ids:
            cache.delete(COHORT_ID_IN_FF_KEY)
            for cohort in Cohort.objects.filter(pk__in=self.cohort_ids):
                update_cohort(cohort)


@mutable_receiver(pre_delete, sender=Experiment)
def delete_experiment_flags(sender, instance, **kwargs):
    FeatureFlag.objects.filter(experiment=instance).update(deleted=True)


class FeatureFlagHashKeyOverride(models.Model):
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "person", "feature_flag_key"],
                name="Unique hash_key for a user/team/feature_flag combo",
            ),
        ]

    # Can't use a foreign key to feature_flag_key directly, since
    # the unique constraint is on (team_id+key), and not just key.
    # A standard id foreign key leads to INNER JOINs everytime we want to get the key
    # and we only ever want to get the key.
    feature_flag_key: models.CharField = models.CharField(max_length=400)
    person: models.ForeignKey = models.ForeignKey("Person", on_delete=models.CASCADE)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    hash_key: models.CharField = models.CharField(max_length=400)


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
        hash_key_overrides: Dict[str, str] = {},
    ):
        self.feature_flag = feature_flag
        self.distinct_id = distinct_id
        self.groups = groups
        self.cache = cache or FlagsMatcherCache(self.feature_flag.team_id)
        self.hash_key_overrides = hash_key_overrides

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
                # Feature Flags don't support OR filtering yet
                expr: Any = properties_to_Q(
                    Filter(data=condition).property_groups.flat, team_id=self.feature_flag.team_id, is_direct_query=True
                )
            else:
                expr = RawSQL("true", [])

            query = query.annotate(**{key: ExpressionWrapper(expr, output_field=BooleanField())})
            fields.append(key)

        return list(query.values_list(*fields))

    @cached_property
    def hashed_identifier(self) -> Optional[str]:
        """
        If aggregating by people, returns distinct_id.

        Otherwise, returns the relevant group_key.

        If relevant group is not passed to the flag, None is returned and handled in get_match.
        """
        if self.feature_flag.aggregation_group_type_index is None:
            if self.feature_flag.ensure_experience_continuity:
                # TODO: Try a global cache
                if self.feature_flag.key in self.hash_key_overrides:
                    return self.hash_key_overrides[self.feature_flag.key]
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


def hash_key_overrides(team_id: int, person_id: int) -> Dict[str, str]:
    feature_flag_to_key_overrides = {}
    for feature_flag, override in FeatureFlagHashKeyOverride.objects.filter(
        person_id=person_id, team=team_id
    ).values_list("feature_flag_key", "hash_key"):
        feature_flag_to_key_overrides[feature_flag] = override

    return feature_flag_to_key_overrides


# Return a Dict with all active flags and their values
def _get_active_feature_flags(
    feature_flags: QuerySet,
    team_id: int,
    distinct_id: str,
    person_id: Optional[int] = None,
    groups: Dict[GroupTypeName, str] = {},
) -> Dict[str, Union[bool, str, None]]:
    cache = FlagsMatcherCache(team_id)
    flags_enabled: Dict[str, Union[bool, str, None]] = {}

    if person_id is not None:
        overrides = hash_key_overrides(team_id, person_id)
    else:
        overrides = {}

    for feature_flag in feature_flags:
        try:
            match = feature_flag.matches(distinct_id, groups, cache, overrides)
            if match:
                flags_enabled[feature_flag.key] = match.variant or True
        except Exception as err:
            capture_exception(err)
    return flags_enabled


# Return feature flags
def get_active_feature_flags(
    team_id: int, distinct_id: str, groups: Dict[GroupTypeName, str] = {}, hash_key_override: Optional[str] = None
) -> Dict[str, Union[bool, str, None]]:

    all_feature_flags = FeatureFlag.objects.filter(team_id=team_id, active=True, deleted=False).only(
        "id", "team_id", "filters", "key", "rollout_percentage", "ensure_experience_continuity"
    )

    flags_have_experience_continuity_enabled = any(
        feature_flag.ensure_experience_continuity for feature_flag in all_feature_flags
    )

    if not flags_have_experience_continuity_enabled:
        return _get_active_feature_flags(all_feature_flags, team_id, distinct_id, groups=groups)

    person_id = (
        PersonDistinctId.objects.filter(distinct_id=distinct_id, team_id=team_id)
        .values_list("person_id", flat=True)
        .first()
    )

    if hash_key_override is not None:
        # setting overrides only when we get an override
        if person_id is None:
            # :TRICKY: Some ingestion delays may mean that `$identify` hasn't yet created
            # the new person on which decide was called.
            # In this case, we can try finding the person_id for the old distinct id.
            # This is safe, since once `$identify` is processed, it would only add the distinct_id to this
            # existing person. If, because of race conditions, a person merge is called for later,
            # then https://github.com/PostHog/posthog/blob/master/plugin-server/src/worker/ingestion/person-state.ts#L421
            # will take care of it^.
            person_id = (
                PersonDistinctId.objects.filter(distinct_id=hash_key_override, team_id=team_id)
                .values_list("person_id", flat=True)
                .first()
            )
            # If even this old person doesn't exist yet, we're facing severe ingestion delays
            # and there's not much we can do, since all person properties based feature flags
            # would fail server side anyway.

        if person_id is not None:
            set_feature_flag_hash_key_overrides(all_feature_flags, team_id, person_id, hash_key_override)

    # :TRICKY: Consistency matters only when personIDs exist
    # as overrides are stored on personIDs.
    # We can optimise by not going down this path when person_id doesn't exist, or
    # no flags have experience continuity enabled
    return _get_active_feature_flags(all_feature_flags, team_id, distinct_id, person_id, groups=groups)


def set_feature_flag_hash_key_overrides(
    feature_flags: QuerySet, team_id: int, person_id: int, hash_key_override: str
) -> None:

    existing_flag_overrides = set(
        FeatureFlagHashKeyOverride.objects.filter(team_id=team_id, person_id=person_id).values_list(
            "feature_flag_key", flat=True
        )
    )
    new_overrides = []
    for feature_flag in feature_flags:
        if feature_flag.ensure_experience_continuity and feature_flag.key not in existing_flag_overrides:
            new_overrides.append(
                FeatureFlagHashKeyOverride(
                    team_id=team_id, person_id=person_id, feature_flag_key=feature_flag.key, hash_key=hash_key_override
                )
            )

    if new_overrides:
        FeatureFlagHashKeyOverride.objects.bulk_create(new_overrides)


# DEPRECATED: This model is no longer used, but it's not deleted to avoid downtime
class FeatureFlagOverride(models.Model):
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "feature_flag", "team"], name="unique feature flag for a user/team combo",
            ),
        ]

    feature_flag: models.ForeignKey = models.ForeignKey("FeatureFlag", on_delete=models.CASCADE)
    user: models.ForeignKey = models.ForeignKey("User", on_delete=models.CASCADE)
    override_value: models.JSONField = models.JSONField()
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
