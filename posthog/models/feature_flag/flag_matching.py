import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from django.db import DatabaseError
from django.db.models.expressions import ExpressionWrapper, RawSQL
from django.db.models.fields import BooleanField
from django.db.models.query import QuerySet
from sentry_sdk.api import capture_exception

from posthog.models.filters import Filter
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.group import Group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.person import Person, PersonDistinctId
from posthog.models.property import GroupTypeIndex, GroupTypeName
from posthog.models.property.property import Property
from posthog.models.utils import execute_with_timeout
from posthog.queries.base import match_property, properties_to_Q

from .feature_flag import (
    FeatureFlag,
    FeatureFlagHashKeyOverride,
    get_feature_flags_for_team_in_cache,
    set_feature_flags_for_team_in_cache,
)

__LONG_SCALE__ = float(0xFFFFFFFFFFFFFFF)

FLAG_MATCHING_QUERY_TIMEOUT_MS = 3 * 1000  # 3 seconds. Any longer and we'll just error out.


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


class FlagsMatcherCache:
    def __init__(self, team_id: int):
        self.team_id = team_id
        self.failed_to_fetch_flags = False

    @cached_property
    def group_types_to_indexes(self) -> Dict[GroupTypeName, GroupTypeIndex]:
        try:
            with execute_with_timeout(FLAG_MATCHING_QUERY_TIMEOUT_MS):
                group_type_mapping_rows = GroupTypeMapping.objects.filter(team_id=self.team_id)
                return {row.group_type: row.group_type_index for row in group_type_mapping_rows}
        except DatabaseError:
            self.failed_to_fetch_flags = True
            return {}

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
        skip_experience_continuity_flags: bool = False,
    ):
        self.feature_flags = feature_flags
        self.distinct_id = distinct_id
        self.groups = groups
        self.cache = cache or FlagsMatcherCache(self.feature_flags[0].team_id)
        self.hash_key_overrides = hash_key_overrides
        self.property_value_overrides = property_value_overrides
        self.group_property_value_overrides = group_property_value_overrides
        self.skip_experience_continuity_flags = skip_experience_continuity_flags

    def get_match(self, feature_flag: FeatureFlag) -> FeatureFlagMatch:
        # If aggregating flag by groups and relevant group type is not passed - flag is off!
        if self.hashed_identifier(feature_flag) is None:
            if self.cache.failed_to_fetch_flags:
                raise DatabaseError("Failed to get group type mapping for team")

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

        payload = None
        return FeatureFlagMatch(
            match=False,
            reason=highest_priority_evaluation_reason,
            condition_index=highest_priority_index,
            payload=payload,
        )

    def get_matches(self) -> Tuple[Dict[str, Union[str, bool]], Dict[str, dict], Dict[str, object], bool]:
        flag_values = {}
        flag_evaluation_reasons = {}
        faced_error_computing_flags = False
        flag_payloads = {}
        for feature_flag in self.feature_flags:
            if self.skip_experience_continuity_flags and feature_flag.ensure_experience_continuity:
                faced_error_computing_flags = True
                continue
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
                faced_error_computing_flags = True
                capture_exception(err)

        return flag_values, flag_evaluation_reasons, flag_payloads, faced_error_computing_flags

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
        with execute_with_timeout(FLAG_MATCHING_QUERY_TIMEOUT_MS):
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
                            override_property_values=target_properties,
                        )

                    if feature_flag.aggregation_group_type_index is None:
                        person_query = person_query.annotate(
                            **{
                                key: ExpressionWrapper(
                                    expr if expr else RawSQL("true", []), output_field=BooleanField()
                                )
                            }
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
                            **{
                                key: ExpressionWrapper(
                                    expr if expr else RawSQL("true", []), output_field=BooleanField()
                                )
                            }
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
    with execute_with_timeout(FLAG_MATCHING_QUERY_TIMEOUT_MS):
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
    skip_experience_continuity_flags: bool = False,
) -> Tuple[Dict[str, Union[str, bool]], Dict[str, dict], Dict[str, object], bool]:
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
            skip_experience_continuity_flags,
        ).get_matches()

    return {}, {}, {}, False


# Return feature flags
def get_all_feature_flags(
    team_id: int,
    distinct_id: str,
    groups: Dict[GroupTypeName, str] = {},
    hash_key_override: Optional[str] = None,
    property_value_overrides: Dict[str, Union[str, int]] = {},
    group_property_value_overrides: Dict[str, Dict[str, Union[str, int]]] = {},
) -> Tuple[Dict[str, Union[str, bool]], Dict[str, dict], Dict[str, object], bool]:

    all_feature_flags = get_feature_flags_for_team_in_cache(team_id)
    if all_feature_flags is None:
        all_feature_flags = set_feature_flags_for_team_in_cache(team_id)

    flags_have_experience_continuity_enabled = any(
        feature_flag.ensure_experience_continuity for feature_flag in all_feature_flags
    )

    if not flags_have_experience_continuity_enabled:
        return _get_all_feature_flags(
            all_feature_flags,
            team_id,
            distinct_id,
            groups=groups,
            property_value_overrides=property_value_overrides,
            group_property_value_overrides=group_property_value_overrides,
        )

    try:
        with execute_with_timeout(FLAG_MATCHING_QUERY_TIMEOUT_MS):
            person_id = (
                PersonDistinctId.objects.filter(distinct_id=distinct_id, team_id=team_id)
                .values_list("person_id", flat=True)
                .first()
            )
    except DatabaseError:
        # database is down, we can't handle experience continuity flags.
        # Treat this same as if there are no experience continuity flags.
        # This automatically sets 'errorsWhileComputingFlags' to True.
        return _get_all_feature_flags(
            all_feature_flags,
            team_id,
            distinct_id,
            groups=groups,
            property_value_overrides=property_value_overrides,
            group_property_value_overrides=group_property_value_overrides,
            skip_experience_continuity_flags=True,
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
            with execute_with_timeout(FLAG_MATCHING_QUERY_TIMEOUT_MS):
                person_id = (
                    PersonDistinctId.objects.filter(distinct_id=hash_key_override, team_id=team_id)
                    .values_list("person_id", flat=True)
                    .first()
                )
            # If even this old person doesn't exist yet, we're facing severe ingestion delays
            # and there's not much we can do, since all person properties based feature flags
            # would fail server side anyway.

        if person_id is not None:
            try:
                set_feature_flag_hash_key_overrides(all_feature_flags, team_id, person_id, hash_key_override)
            except Exception as e:
                # If the database is in read-only mode, we can't handle experience continuity flags.
                # Do not error on decide for this case.
                capture_exception(e)

    # :TRICKY: Consistency matters only when personIDs exist
    # as overrides are stored on personIDs.
    # We can optimise by not going down this path when person_id doesn't exist, or
    # no flags have experience continuity enabled
    return _get_all_feature_flags(
        all_feature_flags,
        team_id,
        distinct_id,
        person_id,
        groups=groups,
        property_value_overrides=property_value_overrides,
        group_property_value_overrides=group_property_value_overrides,
    )


def set_feature_flag_hash_key_overrides(
    feature_flags: List[FeatureFlag], team_id: int, person_id: int, hash_key_override: str
) -> None:

    with execute_with_timeout(FLAG_MATCHING_QUERY_TIMEOUT_MS):
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
        with execute_with_timeout(FLAG_MATCHING_QUERY_TIMEOUT_MS):
            FeatureFlagHashKeyOverride.objects.bulk_create(new_overrides, ignore_conflicts=True)
