import json
from typing import TYPE_CHECKING, Optional, cast

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.cache import cache
from django.db import DatabaseError, models, transaction
from django.db.models import QuerySet
from django.db.models.signals import post_delete, post_save
from django.http import HttpRequest
from django.utils import timezone

import structlog

from posthog.constants import ENRICHED_DASHBOARD_INSIGHT_IDENTIFIER, PropertyOperatorType
from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.cohort import Cohort, CohortOrEmpty
from posthog.models.file_system.file_system_mixin import FileSystemSyncMixin
from posthog.models.file_system.file_system_representation import FileSystemRepresentation
from posthog.models.property import GroupTypeIndex
from posthog.models.property.property import Property, PropertyGroup
from posthog.models.signals import mutable_receiver
from posthog.models.utils import RootTeamMixin

FIVE_DAYS = 60 * 60 * 24 * 5  # 5 days in seconds

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from posthog.models.team import Team


class FeatureFlag(FileSystemSyncMixin, ModelActivityMixin, RootTeamMixin, models.Model):
    # When adding new fields, make sure to update organization_feature_flags.py::copy_flags
    key = models.CharField(max_length=400)
    name = models.TextField(
        blank=True
    )  # contains description for the FF (field name `name` is kept for backwards-compatibility)

    filters = models.JSONField(default=dict)
    rollout_percentage = models.IntegerField(null=True, blank=True)

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(null=True, auto_now=True)
    deleted = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    version = models.IntegerField(default=1, null=True)
    last_modified_by = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="updated_feature_flags",
        db_index=False,
    )

    rollback_conditions = models.JSONField(null=True, blank=True)
    performed_rollback = models.BooleanField(null=True, blank=True)

    ensure_experience_continuity = models.BooleanField(default=False, null=True, blank=True)
    usage_dashboard = models.ForeignKey("Dashboard", on_delete=models.SET_NULL, null=True, blank=True)
    analytics_dashboards: models.ManyToManyField = models.ManyToManyField(
        "Dashboard",
        through="FeatureFlagDashboards",
        related_name="analytics_dashboards",
        related_query_name="analytics_dashboard",
    )
    # whether a feature is sending us rich analytics, like views & interactions.
    has_enriched_analytics = models.BooleanField(default=False, null=True, blank=True)

    is_remote_configuration = models.BooleanField(default=False, null=True, blank=True)
    has_encrypted_payloads = models.BooleanField(default=False, null=True, blank=True)

    EVALUATION_RUNTIME_CHOICES = [
        ("server", "Server"),
        ("client", "Client"),
        ("all", "All"),
    ]
    evaluation_runtime = models.CharField(
        max_length=10,
        choices=EVALUATION_RUNTIME_CHOICES,
        default="all",
        null=True,
        blank=True,
        help_text="Specifies where this feature flag should be evaluated",
    )

    # Cache projection: evaluation_tag_names is stored in Redis but isn't a DB field.
    # This allows us to include evaluation tags in the cached flag data without
    # modifying the FeatureFlag model schema. The Redis cache stores the serialized
    # JSON including evaluation_tags, and when we deserialize, we store them here
    # temporarily to avoid N+1 queries when accessing evaluation tags.
    _evaluation_tag_names: Optional[list[str]] = None

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "key"], name="unique key for team")]

    def __str__(self):
        return f"{self.key} ({self.pk})"

    @classmethod
    def get_file_system_unfiled(cls, team: "Team") -> QuerySet["FeatureFlag"]:
        base_qs = cls.objects.filter(team=team, deleted=False)
        return cls._filter_unfiled_queryset(base_qs, team, type="feature_flag", ref_field="id")

    def get_file_system_representation(self) -> FileSystemRepresentation:
        return FileSystemRepresentation(
            base_folder=self._get_assigned_folder("Unfiled/Feature Flags"),
            type="feature_flag",  # sync with APIScopeObject in scopes.py
            ref=str(self.id),
            name=self.key or "Untitled",
            href=f"/feature_flags/{self.id}",
            meta={
                "created_at": str(self.created_at),
                "created_by": self.created_by_id,
            },
            should_delete=self.deleted,
        )

    def get_analytics_metadata(self) -> dict:
        filter_count = sum(len(condition.get("properties", [])) for condition in self.conditions)
        variants_count = len(self.variants)
        payload_count = len(self._payloads)

        return {
            "groups_count": len(self.conditions),
            "has_variants": variants_count > 0,
            "variants_count": variants_count,
            "has_filters": filter_count > 0,
            "has_rollout_percentage": any(condition.get("rollout_percentage") for condition in self.conditions),
            "filter_count": filter_count,
            "created_at": self.created_at,
            "aggregating_by_groups": self.aggregation_group_type_index is not None,
            "payload_count": payload_count,
        }

    @property
    def conditions(self):
        "Each feature flag can have multiple conditions to match, they are OR-ed together."
        return self.get_filters().get("groups", []) or []

    @property
    def super_conditions(self):
        "Each feature flag can have multiple super conditions to match, they are OR-ed together."
        return self.get_filters().get("super_groups", []) or []

    @property
    def holdout_conditions(self):
        "Each feature flag can have multiple holdout conditions to match, they are OR-ed together."
        return self.get_filters().get("holdout_groups", []) or []

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

    @property
    def usage_dashboard_has_enriched_insights(self) -> bool:
        if not self.usage_dashboard:
            return False

        return any(
            ENRICHED_DASHBOARD_INSIGHT_IDENTIFIER in (tile.insight.name or "")
            for tile in self.usage_dashboard.tiles.all()
            if tile.insight
        )

    @property
    def evaluation_tag_names(self) -> list[str] | None:
        """
        Returns evaluation tag names for this flag.

        Preferred source is the cache-populated list from Redis (set on instances
        as `_evaluation_tag_names`). If not present, falls back to the DB relation
        via `evaluation_tags` → `Tag.name`.
        """
        cached = getattr(self, "_evaluation_tag_names", None)
        if cached is not None:
            return cached

        try:
            return [et.tag.name for et in self.evaluation_tags.select_related("tag").all()]
        except (AttributeError, DatabaseError):
            return None

    def get_filters(self) -> dict:
        if isinstance(self.filters, dict) and "groups" in self.filters:
            return self.filters
        else:
            # :TRICKY: Keep this backwards compatible.
            #   We don't want to migrate to avoid /decide endpoint downtime until this code has been deployed
            return {
                "groups": [
                    {
                        "properties": self.filters.get("properties", []),
                        "rollout_percentage": self.rollout_percentage,
                    }
                ],
            }

    def transform_cohort_filters_for_easy_evaluation(
        self,
        using_database: str = "default",
        seen_cohorts_cache: Optional[dict[int, CohortOrEmpty]] = None,
    ):
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

        if seen_cohorts_cache is None:
            seen_cohorts_cache = {}

        if len(self.get_cohort_ids(using_database=using_database, seen_cohorts_cache=seen_cohorts_cache)) != 1:
            return self.conditions

        cohort_group_rollout = None
        cohort: CohortOrEmpty = None

        parsed_conditions = []
        for condition in self.conditions:
            if condition.get("variant"):
                # variant overrides are not supported for cohort expansion.
                return self.conditions

            cohort_condition = False
            props = condition.get("properties", [])
            cohort_group_rollout = condition.get("rollout_percentage")
            for prop in props:
                if prop.get("type") == "cohort":
                    cohort_condition = True
                    cohort_id = int(prop.get("value"))
                    if cohort_id:
                        if len(props) > 1:
                            # We cannot expand this cohort condition if it's not the only property in its group.
                            return self.conditions
                        try:
                            if cohort_id in seen_cohorts_cache:
                                cohort = seen_cohorts_cache[cohort_id]
                                if not cohort:
                                    return self.conditions
                            else:
                                cohort = Cohort.objects.db_manager(using_database).get(
                                    pk=cohort_id, team__project_id=self.team.project_id, deleted=False
                                )
                                seen_cohorts_cache[cohort_id] = cohort
                        except Cohort.DoesNotExist:
                            seen_cohorts_cache[cohort_id] = ""
                            return self.conditions
            if not cohort_condition:
                # flag group without a cohort filter, let it be as is.
                parsed_conditions.append(condition)

        if not cohort or len(cohort.properties.flat) == 0:
            return self.conditions

        if not all(property.type == "person" for property in cohort.properties.flat):
            return self.conditions

        if any(property.negation for property in cohort.properties.flat):
            # Local evaluation doesn't support negation.
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

            for prop_group in cast(list[PropertyGroup], target_properties.values):
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

    def get_cohort_ids(
        self,
        using_database: str = "default",
        seen_cohorts_cache: Optional[dict[int, CohortOrEmpty]] = None,
        sort_by_topological_order=False,
    ) -> list[int]:
        from posthog.models.cohort.util import get_all_cohort_dependencies, sort_cohorts_topologically

        if seen_cohorts_cache is None:
            seen_cohorts_cache = {}

        cohort_ids = set()
        for condition in self.conditions:
            props = condition.get("properties", [])
            for prop in props:
                if prop.get("type") == "cohort":
                    cohort_id = int(prop.get("value"))
                    try:
                        if cohort_id in seen_cohorts_cache:
                            cohort: CohortOrEmpty = seen_cohorts_cache[cohort_id]
                            if not cohort:
                                continue
                        else:
                            cohort = Cohort.objects.db_manager(using_database).get(
                                pk=cohort_id, team__project_id=self.team.project_id, deleted=False
                            )
                            seen_cohorts_cache[cohort_id] = cohort

                        cohort_ids.add(cohort.pk)
                        cohort_ids.update(
                            [
                                dependency_cohort.pk
                                for dependency_cohort in get_all_cohort_dependencies(
                                    cohort,
                                    using_database=using_database,
                                    seen_cohorts_cache=seen_cohorts_cache,
                                )
                            ]
                        )
                    except Cohort.DoesNotExist:
                        seen_cohorts_cache[cohort_id] = ""
                        continue
        if sort_by_topological_order:
            return sort_cohorts_topologically(cohort_ids, seen_cohorts_cache)

        return list(cohort_ids)

    def scheduled_changes_dispatcher(
        self, payload, user: Optional[AbstractBaseUser] = None, scheduled_change_id: Optional[int] = None
    ):
        from posthog.api.feature_flag import FeatureFlagSerializer

        if "operation" not in payload or "value" not in payload:
            raise Exception("Invalid payload")

        # Store scheduled change context on the instance for activity logging
        if scheduled_change_id is not None:
            self._scheduled_change_context = {"scheduled_change_id": scheduled_change_id}

        http_request = HttpRequest()
        # We kind of cheat here set the request user to the user who created the scheduled change
        # It's not the correct type, but it matches enough to get the job done
        http_request.user = user or self.created_by  # type: ignore
        context = {
            "request": http_request,
            "team_id": self.team_id,
            "project_id": self.team.project_id,
        }

        serializer_data = {}

        if payload["operation"] == "add_release_condition":
            current_filters = self.get_filters()
            current_groups = current_filters.get("groups", [])
            new_groups = payload["value"].get("groups", [])

            serializer_data["filters"] = {**current_filters, "groups": current_groups + new_groups}
        elif payload["operation"] == "update_status":
            serializer_data["active"] = payload["value"]
        elif payload["operation"] == "update_variants":
            current_filters = self.get_filters()
            variant_data = payload["value"]

            new_variants = variant_data.get("variants", [])
            new_payloads = variant_data.get("payloads", {})

            # Validate variant rollout percentages before proceeding
            if new_variants:
                total_rollout = sum(variant.get("rollout_percentage", 0) for variant in new_variants)
                if total_rollout != 100:
                    raise ValueError(f"Invalid variant rollout percentages: sum is {total_rollout}, must be 100")

            # Validate payload keys match variant keys
            variant_keys = {v.get("key") for v in new_variants}
            payload_keys = set(new_payloads.keys()) if new_payloads else set()

            # Only validate payload-variant key matching if both exist and are non-empty
            # Allow no payloads (for variants without payloads) or empty variants
            if payload_keys and variant_keys and not payload_keys.issubset(variant_keys):
                invalid_keys = payload_keys - variant_keys
                raise ValueError(f"Payload keys {invalid_keys} don't match variant keys {variant_keys}")

            updated_multivariate = current_filters.get("multivariate", {})
            updated_multivariate["variants"] = new_variants

            serializer_data["filters"] = {
                **current_filters,
                "multivariate": updated_multivariate,
                "payloads": new_payloads,
            }
        else:
            raise Exception(f"Unrecognized operation: {payload['operation']}")

        serializer = FeatureFlagSerializer(self, data=serializer_data, context=context, partial=True)
        if serializer.is_valid(raise_exception=True):
            serializer.save()

    @property
    def uses_cohorts(self) -> bool:
        for condition in self.conditions:
            props = condition.get("properties") or []
            for prop in props:
                if prop.get("type") == "cohort":
                    return True
        return False


@mutable_receiver([post_save, post_delete], sender=FeatureFlag)
def refresh_flag_cache_on_updates(sender, instance, **kwargs):
    # Defer cache update until after the transaction commits
    # This ensures the database has the new data before we query it
    transaction.on_commit(lambda: set_feature_flags_for_team_in_cache(instance.team.project_id))


class FeatureFlagHashKeyOverride(models.Model):
    # Can't use a foreign key to feature_flag_key directly, since
    # the unique constraint is on (team_id+key), and not just key.
    # A standard id foreign key leads to INNER JOINs every time we want to get the key
    # and we only ever want to get the key.
    feature_flag_key = models.CharField(max_length=400)
    person = models.ForeignKey("Person", on_delete=models.CASCADE)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    hash_key = models.CharField(max_length=400)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "person", "feature_flag_key"],
                name="Unique hash_key for a user/team/feature_flag combo",
            )
        ]


# DEPRECATED: This model is no longer used, but it's not deleted to avoid downtime
class FeatureFlagOverride(models.Model):
    feature_flag = models.ForeignKey("FeatureFlag", on_delete=models.CASCADE)
    user = models.ForeignKey("User", on_delete=models.CASCADE)
    override_value = models.JSONField()
    team = models.ForeignKey("Team", on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "feature_flag", "team"],
                name="unique feature flag for a user/team combo",
            )
        ]


def set_feature_flags_for_team_in_cache(
    project_id: int,
    feature_flags: Optional[list[FeatureFlag]] = None,
    using_database: str = "default",
) -> list[FeatureFlag]:
    from django.contrib.postgres.aggregates import ArrayAgg
    from django.db.models import Q

    from posthog.api.feature_flag import MinimalFeatureFlagSerializer

    if feature_flags is not None:
        all_feature_flags = feature_flags
    else:
        # Single-shot query: flags plus evaluation tag names aggregated to a string array.
        # We use ArrayAgg to fetch all evaluation tag names in one query instead of
        # doing a separate query per flag. This is crucial for performance when we have
        # many flags. The evaluation tags are stored as a many-to-many relationship
        # through FeatureFlagEvaluationTag, but we aggregate them here for efficiency.
        qs = (
            FeatureFlag.objects.db_manager(using_database)
            .filter(team__project_id=project_id, active=True, deleted=False)
            .annotate(
                evaluation_tag_names_agg=ArrayAgg(
                    "evaluation_tags__tag__name",
                    filter=Q(evaluation_tags__isnull=False),
                    distinct=True,
                )
            )
        )
        all_feature_flags = list(qs)
        # Transfer the aggregated tag names to the _evaluation_tag_names attribute
        # so the serializer can access them without additional queries. This is a
        # cache projection pattern - we're storing derived data on the model instance
        # that will be serialized to Redis.
        for _flag in all_feature_flags:
            try:
                _flag._evaluation_tag_names = getattr(_flag, "evaluation_tag_names_agg", None)
            except AttributeError:
                # evaluation_tag_names_agg field missing from aggregation query
                _flag._evaluation_tag_names = None

    serialized_flags = MinimalFeatureFlagSerializer(all_feature_flags, many=True).data

    try:
        cache.set(f"team_feature_flags_{project_id}", json.dumps(serialized_flags), FIVE_DAYS)
    except Exception:
        # redis is unavailable
        logger.exception("Redis is unavailable")
        capture_exception()

    return all_feature_flags


def get_feature_flags_for_team_in_cache(project_id: int) -> Optional[list[FeatureFlag]]:
    try:
        flag_data = cache.get(f"team_feature_flags_{project_id}")
    except Exception:
        # redis is unavailable
        logger.exception("Redis is unavailable")
        return None

    if flag_data is not None:
        try:
            parsed_data = json.loads(flag_data)
            flags = []
            for flag_data in parsed_data:
                # Cache projection pattern: evaluation_tags is included in the Redis cache
                # even though it's not a field on the FeatureFlag model. We extract it
                # before creating the model instance and store it as a temporary attribute.
                # This avoids N+1 queries when the Rust service needs to access evaluation
                # tags for many flags at once.
                evaluation_tags_list = flag_data.pop("evaluation_tags", None)
                flag = FeatureFlag(**flag_data)
                # Store the evaluation tags as a private attribute. The evaluation_tag_names
                # property will check this first before falling back to a database query.
                # This makes cache retrieval extremely fast - no DB queries needed.
                flag._evaluation_tag_names = evaluation_tags_list
                flags.append(flag)
            return flags
        except Exception as e:
            logger.exception("Error parsing flags from cache")
            capture_exception(e)
            return None

    return None


class FeatureFlagDashboards(models.Model):
    feature_flag = models.ForeignKey("FeatureFlag", on_delete=models.CASCADE)
    dashboard = models.ForeignKey("Dashboard", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["feature_flag", "dashboard"],
                name="unique feature flag for a dashboard",
            )
        ]


class FeatureFlagEvaluationTag(models.Model):
    """
    Marks an existing tag as also being an evaluation constraint for a feature flag.
    When a tag is marked as an evaluation tag, it serves dual purpose:
    1. It remains an organizational tag (via the TaggedItem relationship)
    2. It acts as an evaluation constraint - the flag will only evaluate when
       the SDK/client provides matching environment tags
    This allows for user-specified evaluation environments like "docs-page",
    "marketing-site", "app", etc.
    """

    feature_flag = models.ForeignKey("FeatureFlag", on_delete=models.CASCADE, related_name="evaluation_tags")
    tag = models.ForeignKey("Tag", on_delete=models.CASCADE, related_name="evaluation_flags")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [["feature_flag", "tag"]]

    def __str__(self) -> str:
        return f"{self.feature_flag.key} - {self.tag.name}"
