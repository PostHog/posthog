import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union, cast

from django.core.cache import cache
from django.db import models
from django.db.models.expressions import ExpressionWrapper, RawSQL
from django.db.models.fields import BooleanField
from django.db.models.query import QuerySet
from django.db.models.signals import pre_delete
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from sentry_sdk.api import capture_exception

from posthog.client import sync_execute
from posthog.constants import AvailableFeature, PropertyOperatorType
from posthog.models.cohort import Cohort
from posthog.models.experiment import Experiment
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.group import Group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.organization import OrganizationMembership
from posthog.models.property import GroupTypeIndex, GroupTypeName
from posthog.models.property.property import Property, PropertyGroup
from posthog.models.signals import mutable_receiver
from posthog.models.team.team import Team
from posthog.queries.base import match_property, properties_to_Q

from .filters import Filter
from .person import Person, PersonDistinctId

__LONG_SCALE__ = float(0xFFFFFFFFFFFFFFF)


class FeatureFlagMatchReason(str, Enum):
    CONDITION_MATCH = "condition_match"
    NO_CONDITION_MATCH = "no_condition_match"
    OUT_OF_ROLLOUT_BOUND = "out_of_rollout_bound"
    NO_GROUP_TYPE = "no_group_type"

    def score(self):
        if self == FeatureFlagMatchReason.CONDITION_MATCH:
            return 3
        if self == FeatureFlagMatchReason.NO_GROUP_TYPE:
            return 2
        if self == FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND:
            return 1
        if self == FeatureFlagMatchReason.NO_CONDITION_MATCH:
            return 0

        return -1

    def __lt__(self, other):
        if self.__class__ is other.__class__:
            return self.score() < other.score()

        raise NotImplementedError(f"Cannot compare {self.__class__} and {other.__class__}")


@dataclass(frozen=True)
class FeatureFlagMatch:
    match: bool = False
    variant: Optional[str] = None
    reason: FeatureFlagMatchReason = FeatureFlagMatchReason.NO_CONDITION_MATCH
    condition_index: Optional[int] = None
    payload: Optional[object] = None


class FeatureFlag(models.Model):
    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "key"], name="unique key for team")]

    key: models.CharField = models.CharField(max_length=400)
    name: models.TextField = models.TextField(
        blank=True
    )  # contains description for the FF (field name `name` is kept for backwards-compatibility)

    filters: models.JSONField = models.JSONField(default=dict)
    rollout_percentage: models.IntegerField = models.IntegerField(null=True, blank=True)

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    deleted: models.BooleanField = models.BooleanField(default=False)
    active: models.BooleanField = models.BooleanField(default=True)

    rollback_conditions: models.JSONField = models.JSONField(null=True, blank=True)
    performed_rollback: models.BooleanField = models.BooleanField(null=True, blank=True)

    ensure_experience_continuity: models.BooleanField = models.BooleanField(default=False, null=True, blank=True)

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
    def _payloads(self):
        return self.get_filters().get("payloads", {}) or {}

    def get_payload(self, match_val: str) -> Optional[object]:
        return self._payloads.get(match_val, None)

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
                ],
                "payloads": self.filters.get("payloads", {}),
            }

    def transform_cohort_filters_for_easy_evaluation(self):
        """
        Expands cohort filters into person property filters when possible.
        This allows for easy local flag evaluation.
        """
        # Expansion depends on number of conditions on the flag.
        # If flag has only the cohort condition, we get more freedom to maneuver in the cohort expansion.
        # If flag has multiple conditions, we can only expand the cohort condition if it's a single property group.
        # Also support only a single cohort expansion. i.e. a flag with multiple cohort conditions will not be expanded.
        # Few more edge cases are possible here, where expansion is possible, but it doesn't seem
        # worth it trying to catch all of these.

        if len(self.cohort_ids) != 1:
            return self.conditions

        cohort_group_rollout = None
        cohort: Optional[Cohort] = None

        parsed_conditions = []
        for condition in self.conditions:
            cohort_condition = False
            props = condition.get("properties", [])
            cohort_group_rollout = condition.get("rollout_percentage")
            for prop in props:
                if prop.get("type") == "cohort":
                    cohort_condition = True
                    cohort_id = prop.get("value")
                    if cohort_id:
                        if len(props) > 1:
                            # We cannot expand this cohort condition if it's not the only property in its group.
                            return self.conditions
                        try:
                            cohort = Cohort.objects.get(pk=cohort_id)
                        except Cohort.DoesNotExist:
                            return self.conditions
            if not cohort_condition:
                # flag group without a cohort filter, let it be as is.
                parsed_conditions.append(condition)

        if not cohort or len(cohort.properties.flat) == 0:
            return self.conditions

        if not all(property.type == "person" for property in cohort.properties.flat):
            return self.conditions

        # all person properties, so now if we can express the cohort as feature flag groups, we'll be golden.

        # If there's only one effective property group, we can always express this as feature flag groups.
        # A single ff group, if cohort properties are AND'ed together.
        # Multiple ff groups, if cohort properties are OR'ed together.
        from posthog.models.property.util import clear_excess_levels

        target_properties = clear_excess_levels(cohort.properties)

        if isinstance(target_properties, Property):
            # cohort was effectively a single property.
            parsed_conditions.append(
                {
                    "properties": [target_properties.to_dict()],
                    "rollout_percentage": cohort_group_rollout,
                }
            )

        elif isinstance(target_properties.values[0], Property):
            # Property Group of properties
            if target_properties.type == PropertyOperatorType.AND:
                parsed_conditions.append(
                    {
                        "properties": [prop.to_dict() for prop in target_properties.values],
                        "rollout_percentage": cohort_group_rollout,
                    }
                )
            else:
                # cohort OR requires multiple ff group
                for prop in target_properties.values:
                    parsed_conditions.append(
                        {
                            "properties": [prop.to_dict()],
                            "rollout_percentage": cohort_group_rollout,
                        }
                    )
        else:
            # If there's nested property groups, we need to express that as OR of ANDs.
            # Being a bit dumb here, and not trying to apply De Morgan's law to coerce AND of ORs into OR of ANDs.
            if target_properties.type == PropertyOperatorType.AND:
                return self.conditions

            for prop_group in cast(List[PropertyGroup], target_properties.values):
                if (
                    len(prop_group.values) == 0
                    or not isinstance(prop_group.values[0], Property)
                    or (prop_group.type == PropertyOperatorType.OR and len(prop_group.values) > 1)
                ):
                    # too nested or invalid, bail out
                    return self.conditions

                parsed_conditions.append(
                    {
                        "properties": [prop.to_dict() for prop in prop_group.values],
                        "rollout_percentage": cohort_group_rollout,
                    }
                )

        return parsed_conditions

    @property
    def cohort_ids(self) -> List[int]:
        cohort_ids = []
        for condition in self.conditions:
            props = condition.get("properties", [])
            for prop in props:
                if prop.get("type") == "cohort":
                    cohort_id = prop.get("value")
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

    def __str__(self):
        return f"{self.key} ({self.pk})"


@mutable_receiver(pre_delete, sender=Experiment)
def delete_experiment_flags(sender, instance, **kwargs):
    FeatureFlag.objects.filter(experiment=instance).update(deleted=True)


class FeatureFlagHashKeyOverride(models.Model):
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "person", "feature_flag_key"], name="Unique hash_key for a user/team/feature_flag combo"
            )
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
        feature_flags: List[FeatureFlag],
        distinct_id: str,
        groups: Dict[GroupTypeName, str] = {},
        cache: Optional[FlagsMatcherCache] = None,
        hash_key_overrides: Dict[str, str] = {},
        property_value_overrides: Dict[str, Union[str, int]] = {},
        group_property_value_overrides: Dict[str, Dict[str, Union[str, int]]] = {},
    ):
        self.feature_flags = feature_flags
        self.distinct_id = distinct_id
        self.groups = groups
        self.cache = cache or FlagsMatcherCache(self.feature_flags[0].team_id)
        self.hash_key_overrides = hash_key_overrides
        self.property_value_overrides = property_value_overrides
        self.group_property_value_overrides = group_property_value_overrides

    def get_match(self, feature_flag: FeatureFlag) -> FeatureFlagMatch:
        # If aggregating flag by groups and relevant group type is not passed - flag is off!
        if self.hashed_identifier(feature_flag) is None:
            return FeatureFlagMatch(match=False, reason=FeatureFlagMatchReason.NO_GROUP_TYPE)

        highest_priority_evaluation_reason = FeatureFlagMatchReason.NO_CONDITION_MATCH
        highest_priority_index = 0
        # Stable sort conditions with variant overrides to the top. This ensures that if overrides are present, they are
        # evaluated first, and the variant override is applied to the first matching condition.
        # :TRICKY: We need to include the enumeration index before the sort so the flag evaluation reason gets the right condition index.
        sorted_flag_conditions = sorted(
            enumerate(feature_flag.conditions),
            key=lambda condition_tuple: 0 if condition_tuple[1].get("variant") else 1,
        )
        for index, condition in sorted_flag_conditions:
            is_match, evaluation_reason = self.is_condition_match(feature_flag, condition, index)
            if is_match:
                variant_override = condition.get("variant")
                if variant_override in [variant["key"] for variant in feature_flag.variants]:
                    variant = variant_override
                else:
                    variant = self.get_matching_variant(feature_flag)

                payload = self.get_matching_payload(is_match, variant, feature_flag)
                return FeatureFlagMatch(
                    match=True, variant=variant, reason=evaluation_reason, condition_index=index, payload=payload
                )

            highest_priority_evaluation_reason, highest_priority_index = self.get_highest_priority_match_evaluation(
                highest_priority_evaluation_reason, highest_priority_index, evaluation_reason, index
            )

        payload = self.get_matching_payload(False, None, feature_flag)
        return FeatureFlagMatch(
            match=False,
            reason=highest_priority_evaluation_reason,
            condition_index=highest_priority_index,
            payload=payload,
        )

    def get_matches(self) -> Tuple[Dict[str, Union[str, bool]], Dict[str, dict], Dict[str, object]]:
        flag_values = {}
        flag_evaluation_reasons = {}
        flag_payloads = {}
        for feature_flag in self.feature_flags:
            try:
                flag_match = self.get_match(feature_flag)
                if flag_match.match:
                    flag_values[feature_flag.key] = flag_match.variant or True
                else:
                    flag_values[feature_flag.key] = False

                if flag_match.payload:
                    flag_payloads[feature_flag.key] = flag_match.payload

                flag_evaluation_reasons[feature_flag.key] = {
                    "reason": flag_match.reason,
                    "condition_index": flag_match.condition_index,
                }
            except Exception as err:
                capture_exception(err)
        return flag_values, flag_evaluation_reasons, flag_payloads

    def get_matching_variant(self, feature_flag: FeatureFlag) -> Optional[str]:
        for variant in self.variant_lookup_table(feature_flag):
            if (
                self.get_hash(feature_flag, salt="variant") >= variant["value_min"]
                and self.get_hash(feature_flag, salt="variant") < variant["value_max"]
            ):
                return variant["key"]
        return None

    def get_matching_payload(
        self, is_match: bool, match_variant: Optional[str], feature_flag: FeatureFlag
    ) -> Optional[object]:
        if is_match:
            if match_variant:
                return feature_flag.get_payload(match_variant)
            else:
                return feature_flag.get_payload("true")
        else:
            return None

    def is_condition_match(
        self, feature_flag: FeatureFlag, condition: Dict, condition_index: int
    ) -> Tuple[bool, FeatureFlagMatchReason]:
        rollout_percentage = condition.get("rollout_percentage")
        if len(condition.get("properties", [])) > 0:
            properties = Filter(data=condition).property_groups.flat
            if self.can_compute_locally(properties, feature_flag.aggregation_group_type_index):
                # :TRICKY: If overrides are enough to determine if a condition is a match,
                # we can skip checking the query.
                # This ensures match even if the person hasn't been ingested yet.
                target_properties = self.property_value_overrides
                if feature_flag.aggregation_group_type_index is not None:
                    target_properties = self.group_property_value_overrides.get(
                        self.cache.group_type_index_to_name[feature_flag.aggregation_group_type_index], {}
                    )
                condition_match = all(match_property(property, target_properties) for property in properties)
            else:
                condition_match = self._condition_matches(feature_flag, condition_index)

            if not condition_match:
                return False, FeatureFlagMatchReason.NO_CONDITION_MATCH
            elif rollout_percentage is None:
                return True, FeatureFlagMatchReason.CONDITION_MATCH

        if rollout_percentage is not None and self.get_hash(feature_flag) > (rollout_percentage / 100):
            return False, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND

        return True, FeatureFlagMatchReason.CONDITION_MATCH

    def _condition_matches(self, feature_flag: FeatureFlag, condition_index: int) -> bool:
        return self.query_conditions.get(f"flag_{feature_flag.pk}_condition_{condition_index}", False)

    # Define contiguous sub-domains within [0, 1].
    # By looking up a random hash value, you can find the associated variant key.
    # e.g. the first of two variants with 50% rollout percentage will have value_max: 0.5
    # and the second will have value_min: 0.5 and value_max: 1.0
    def variant_lookup_table(self, feature_flag: FeatureFlag):
        lookup_table = []
        value_min = 0
        for variant in feature_flag.variants:
            value_max = value_min + variant["rollout_percentage"] / 100
            lookup_table.append({"value_min": value_min, "value_max": value_max, "key": variant["key"]})
            value_min = value_max
        return lookup_table

    @cached_property
    def query_conditions(self) -> Dict[str, bool]:

        team_id = self.feature_flags[0].team_id
        person_query: QuerySet = Person.objects.filter(
            team_id=team_id, persondistinctid__distinct_id=self.distinct_id, persondistinctid__team_id=team_id
        )
        basic_group_query: QuerySet = Group.objects.filter(team_id=team_id)
        group_query_per_group_type_mapping: Dict[GroupTypeIndex, Tuple[QuerySet, List[str]]] = {}
        # :TRICKY: Create a queryset for each group type that uniquely identifies a group, based on the groups passed in.
        # If no groups for a group type are passed in, we can skip querying for that group type,
        # since the result will always be `false`.
        for group_type, group_key in self.groups.items():
            group_type_index = self.cache.group_types_to_indexes.get(group_type)
            if group_type_index is not None:
                # a tuple of querySet and field names
                group_query_per_group_type_mapping[group_type_index] = (
                    basic_group_query.filter(group_type_index=group_type_index, group_key=group_key),
                    [],
                )

        person_fields = []

        for feature_flag in self.feature_flags:
            for index, condition in enumerate(feature_flag.conditions):
                key = f"flag_{feature_flag.pk}_condition_{index}"
                expr: Any = None
                if len(condition.get("properties", {})) > 0:
                    # Feature Flags don't support OR filtering yet
                    target_properties = self.property_value_overrides
                    if feature_flag.aggregation_group_type_index is not None:
                        target_properties = self.group_property_value_overrides.get(
                            self.cache.group_type_index_to_name[feature_flag.aggregation_group_type_index], {}
                        )
                    expr = properties_to_Q(
                        Filter(data=condition).property_groups.flat,
                        team_id=team_id,
                        is_direct_query=True,
                        override_property_values=target_properties,
                    )

                if feature_flag.aggregation_group_type_index is None:
                    person_query = person_query.annotate(
                        **{key: ExpressionWrapper(expr if expr else RawSQL("true", []), output_field=BooleanField())}
                    )
                    person_fields.append(key)
                else:
                    if feature_flag.aggregation_group_type_index not in group_query_per_group_type_mapping:
                        # ignore flags that didn't have the right groups passed in
                        continue
                    group_query, group_fields = group_query_per_group_type_mapping[
                        feature_flag.aggregation_group_type_index
                    ]
                    group_query = group_query.annotate(
                        **{key: ExpressionWrapper(expr if expr else RawSQL("true", []), output_field=BooleanField())}
                    )
                    group_fields.append(key)
                    group_query_per_group_type_mapping[feature_flag.aggregation_group_type_index] = (
                        group_query,
                        group_fields,
                    )

        all_conditions = {}
        if len(person_fields) > 0:
            person_query = person_query.values(*person_fields)
            if len(person_query) > 0:
                all_conditions = {**person_query[0]}

        for group_query, group_fields in group_query_per_group_type_mapping.values():
            group_query = group_query.values(*group_fields)
            if len(group_query) > 0:
                assert len(group_query) == 1, f"Expected 1 group query result, got {len(group_query)}"
                all_conditions = {**all_conditions, **group_query[0]}

        return all_conditions

    def hashed_identifier(self, feature_flag: FeatureFlag) -> Optional[str]:
        """
        If aggregating by people, returns distinct_id.

        Otherwise, returns the relevant group_key.

        If relevant group is not passed to the flag, None is returned and handled in get_match.
        """
        if feature_flag.aggregation_group_type_index is None:
            if feature_flag.ensure_experience_continuity:
                # TODO: Try a global cache
                if feature_flag.key in self.hash_key_overrides:
                    return self.hash_key_overrides[feature_flag.key]
            return self.distinct_id
        else:
            # :TRICKY: If aggregating by groups
            group_type_name = self.cache.group_type_index_to_name.get(feature_flag.aggregation_group_type_index)
            group_key = self.groups.get(group_type_name)  # type: ignore
            return group_key

    # This function takes a identifier and a feature flag key and returns a float between 0 and 1.
    # Given the same identifier and key, it'll always return the same float. These floats are
    # uniformly distributed between 0 and 1, so if we want to show this feature to 20% of traffic
    # we can do _hash(key, identifier) < 0.2
    def get_hash(self, feature_flag: FeatureFlag, salt="") -> float:
        hash_key = f"{feature_flag.key}.{self.hashed_identifier(feature_flag)}{salt}"
        hash_val = int(hashlib.sha1(hash_key.encode("utf-8")).hexdigest()[:15], 16)
        return hash_val / __LONG_SCALE__

    def can_compute_locally(
        self, properties: List[Property], group_type_index: Optional[GroupTypeIndex] = None
    ) -> bool:
        target_properties = self.property_value_overrides
        if group_type_index is not None:
            target_properties = self.group_property_value_overrides.get(
                self.cache.group_type_index_to_name[group_type_index], {}
            )
        for property in properties:
            if property.key not in target_properties:
                return False
            if property.operator == "is_not_set":
                return False
        return True

    def get_highest_priority_match_evaluation(
        self,
        current_match: FeatureFlagMatchReason,
        current_index: int,
        new_match: FeatureFlagMatchReason,
        new_index: int,
    ):
        if current_match <= new_match:
            return new_match, new_index

        return current_match, current_index


def hash_key_overrides(team_id: int, person_id: int) -> Dict[str, str]:
    feature_flag_to_key_overrides = {}
    for feature_flag, override in FeatureFlagHashKeyOverride.objects.filter(
        person_id=person_id, team=team_id
    ).values_list("feature_flag_key", "hash_key"):
        feature_flag_to_key_overrides[feature_flag] = override

    return feature_flag_to_key_overrides


# Return a Dict with all flags and their values
def _get_all_feature_flags(
    feature_flags: List[FeatureFlag],
    team_id: int,
    distinct_id: str,
    person_id: Optional[int] = None,
    groups: Dict[GroupTypeName, str] = {},
    property_value_overrides: Dict[str, Union[str, int]] = {},
    group_property_value_overrides: Dict[str, Dict[str, Union[str, int]]] = {},
) -> Tuple[Dict[str, Union[str, bool]], Dict[str, dict], Dict[str, object]]:
    cache = FlagsMatcherCache(team_id)

    if person_id is not None:
        overrides = hash_key_overrides(team_id, person_id)
    else:
        overrides = {}

    if feature_flags:
        return FeatureFlagMatcher(
            feature_flags,
            distinct_id,
            groups,
            cache,
            overrides,
            property_value_overrides,
            group_property_value_overrides,
        ).get_matches()

    return {}, {}, {}


# Return feature flags
def get_all_feature_flags(
    team_id: int,
    distinct_id: str,
    groups: Dict[GroupTypeName, str] = {},
    hash_key_override: Optional[str] = None,
    property_value_overrides: Dict[str, Union[str, int]] = {},
    group_property_value_overrides: Dict[str, Dict[str, Union[str, int]]] = {},
) -> Tuple[Dict[str, Union[str, bool]], Dict[str, dict], Dict[str, object]]:

    all_feature_flags = FeatureFlag.objects.filter(team_id=team_id, active=True, deleted=False).only(
        "id", "team_id", "filters", "key", "rollout_percentage", "ensure_experience_continuity"
    )

    flags_have_experience_continuity_enabled = any(
        feature_flag.ensure_experience_continuity for feature_flag in all_feature_flags
    )

    if not flags_have_experience_continuity_enabled:
        return _get_all_feature_flags(
            list(all_feature_flags),
            team_id,
            distinct_id,
            groups=groups,
            property_value_overrides=property_value_overrides,
            group_property_value_overrides=group_property_value_overrides,
        )

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
    return _get_all_feature_flags(
        list(all_feature_flags),
        team_id,
        distinct_id,
        person_id,
        groups=groups,
        property_value_overrides=property_value_overrides,
        group_property_value_overrides=group_property_value_overrides,
    )


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
        # :TRICKY: regarding the ignore_conflicts parameter:
        # This can happen if the same person is being processed by multiple workers
        # / we got multiple requests for the same person
        # at the same time. In this case, we can safely ignore the error.
        # We don't want to return an error response for `/decide` just because of this.
        FeatureFlagHashKeyOverride.objects.bulk_create(new_overrides, ignore_conflicts=True)


def get_user_blast_radius(team: Team, feature_flag_condition: dict, group_type_index: Optional[GroupTypeIndex] = None):

    from posthog.queries.person_query import PersonQuery

    # No rollout % calculations here, since it makes more sense to compute that on the frontend
    properties = feature_flag_condition.get("properties") or []

    if group_type_index is not None:

        try:
            from ee.clickhouse.queries.groups_join_query import GroupsJoinQuery
        except Exception:
            return 0, 0

        if len(properties) > 0:
            filter = Filter(data=feature_flag_condition, team=team)

            for property in filter.property_groups.flat:
                if property.group_type_index is None or (property.group_type_index != group_type_index):
                    raise ValidationError("Invalid group type index for feature flag condition.")

            groups_query, groups_query_params = GroupsJoinQuery(filter, team.id).get_filter_query(
                group_type_index=group_type_index
            )

            total_affected_count = sync_execute(
                f"""
                SELECT count(1) FROM (
                    {groups_query}
                )
            """,
                groups_query_params,
            )[0][0]
        else:
            total_affected_count = team.groups_seen_so_far(group_type_index)

        return total_affected_count, team.groups_seen_so_far(group_type_index)

    if len(properties) > 0:
        filter = Filter(data=feature_flag_condition, team=team)
        cohort_filters = []
        for property in filter.property_groups.flat:
            if property.type in ["cohort", "precalculated-cohort", "static-cohort"]:
                cohort_filters.append(property)

        target_cohort = None

        if len(cohort_filters) == 1:
            try:
                target_cohort = Cohort.objects.get(id=cohort_filters[0].value, team=team)
            except Cohort.DoesNotExist:
                pass
            finally:
                cohort_filters = []

        person_query, person_query_params = PersonQuery(
            filter, team.id, cohort=target_cohort, cohort_filters=cohort_filters
        ).get_query()

        total_count = sync_execute(
            f"""
            SELECT count(1) FROM (
                {person_query}
            )
        """,
            person_query_params,
        )[0][0]

    else:
        total_count = team.persons_seen_so_far

    blast_radius = total_count
    total_users = team.persons_seen_so_far

    return blast_radius, total_users


def can_user_edit_feature_flag(request, feature_flag):
    # self hosted check for enterprise models that may not exist
    try:
        from ee.models.feature_flag_role_access import FeatureFlagRoleAccess
        from ee.models.organization_resource_access import OrganizationResourceAccess
    except:
        return True
    else:
        if not request.user.organization.is_feature_available(AvailableFeature.ROLE_BASED_ACCESS):
            return True
        if feature_flag.created_by == request.user:
            return True
        if (
            request.user.organization_memberships.get(organization=request.user.organization).level
            >= OrganizationMembership.Level.ADMIN
        ):
            return True
        all_role_memberships = request.user.role_memberships.select_related("role").all()
        try:
            feature_flag_resource_access = OrganizationResourceAccess.objects.get(
                organization=request.user.organization, resource=OrganizationResourceAccess.Resources.FEATURE_FLAGS
            )
            if feature_flag_resource_access.access_level >= OrganizationResourceAccess.AccessLevel.CAN_ALWAYS_EDIT:
                return True
            org_level = feature_flag_resource_access.access_level
        except OrganizationResourceAccess.DoesNotExist:
            org_level = OrganizationResourceAccess.AccessLevel.CAN_ALWAYS_EDIT

        role_level = max([membership.role.feature_flags_access_level for membership in all_role_memberships], default=0)

        if role_level == 0:
            final_level = org_level
        else:
            final_level = role_level
        if final_level == OrganizationResourceAccess.AccessLevel.CAN_ONLY_VIEW:
            can_edit = FeatureFlagRoleAccess.objects.filter(
                feature_flag__id=feature_flag.pk,
                role__id__in=[membership.role.pk for membership in all_role_memberships],
            ).exists()
            return can_edit
        else:
            return final_level == OrganizationResourceAccess.AccessLevel.CAN_ALWAYS_EDIT


# DEPRECATED: This model is no longer used, but it's not deleted to avoid downtime
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
