import json
from typing import Dict, List, Optional, cast

from django.core.cache import cache
from django.db import models
from django.db.models.signals import pre_delete
from django.utils import timezone
from sentry_sdk.api import capture_exception

from posthog.constants import PropertyOperatorType
from posthog.models.cohort import Cohort
from posthog.models.experiment import Experiment
from posthog.models.property import GroupTypeIndex
from posthog.models.property.property import Property, PropertyGroup
from posthog.models.signals import mutable_receiver


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

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        set_feature_flags_for_team_in_cache(self.team_id)

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        set_feature_flags_for_team_in_cache(self.team_id)

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


def set_feature_flags_for_team_in_cache(
    team_id: int, feature_flags: Optional[List[FeatureFlag]] = None
) -> List[FeatureFlag]:
    from posthog.api.feature_flag import MinimalFeatureFlagSerializer

    if feature_flags is not None:
        all_feature_flags = feature_flags
    else:
        all_feature_flags = list(FeatureFlag.objects.filter(team_id=team_id, active=True, deleted=False))

    serialized_flags = MinimalFeatureFlagSerializer(all_feature_flags, many=True).data

    cache.set(f"team_feature_flags_{team_id}", json.dumps(serialized_flags), None)

    return all_feature_flags


def get_feature_flags_for_team_in_cache(team_id: int) -> Optional[List[FeatureFlag]]:
    try:
        flag_data = cache.get(f"team_feature_flags_{team_id}")
    except Exception:
        # redis is unavailable
        return None

    if flag_data is not None:
        try:
            parsed_data = json.loads(flag_data)
            return [FeatureFlag(**flag) for flag in parsed_data]
        except Exception as e:
            capture_exception(e)
            return None

    return None
