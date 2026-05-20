from datetime import UTC, datetime
from typing import Any, Optional

from django.core.cache import cache
from django.db import models, transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

import structlog
from celery import shared_task
from rest_framework import serializers

from posthog.schema import ProductIntentContext, ProductKey

from posthog.exceptions_capture import capture_exception
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.hog_flow.hog_flow import HogFlow
from posthog.models.insight import Insight
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import RootTeamMixin, UUIDTModel
from posthog.scoping_audit import skip_team_scope_audit
from posthog.session_recordings.models.session_recording_event import SessionRecordingViewed
from posthog.utils import get_instance_realm, get_safe_cache, safe_cache_delete, safe_cache_set

from products.dashboards.backend.models.dashboard import Dashboard
from products.error_tracking.backend.models import ErrorTrackingIssue
from products.event_definitions.backend.models.event_definition import EventDefinition
from products.experiments.backend.models.experiment import Experiment
from products.product_tours.backend.models import ProductTour
from products.surveys.backend.models import Survey

logger = structlog.get_logger(__name__)

"""
How to use this model:

Product intents are indicators that someone showed an interest in a given product.
They are triggered from the frontend when the user performs certain actions, like
selecting a product during onboarding or clicking on a certain button.

Some buttons that show product intent are frequently used by all users of the product,
so we need to know if it's a new product intent, or if it's just regular usage. We
can use the `activated_at` field to know when a product intent is activated.

The `activated_at` field is set by checking against certain criteria that differs for
each product. For instance, for the data warehouse product, we check if the user has
created any DataVisualizationNode insights in the 30 days after the product intent
was created. Each product needs to implement a method that checks for activation
criteria.

We shouldn't use this model and the `activated_at` field in place of sending events
about product usage because that limits our data exploration later. Definitely continue
sending events for product usage that we may want to track for any reason, along with
calculating activation here.

Note: single-event activation metrics that can also happen at the same time the intent
is created won't have tracking events sent for them. Unless you want to solve this,
make activation metrics require multiple things to happen.
"""


class ProductIntentSerializer(serializers.Serializer):
    """
    Serializer for validating product intent data.
    This is used when registering new product intents via the API.
    """

    metadata = serializers.DictField(required=False, default=dict)
    product_type = serializers.ChoiceField(required=True, choices=list(ProductKey))
    intent_context = serializers.ChoiceField(required=False, choices=list(ProductIntentContext))


class ProductIntent(UUIDTModel, RootTeamMixin):
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    product_type = models.CharField(max_length=255)
    onboarding_completed_at = models.DateTimeField(null=True, blank=True)
    contexts = models.JSONField(default=dict, blank=True, null=True)
    activated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="The date the org completed activation for the product. Generally only used to know if we should continue updating the product_intent row.",
    )
    activation_last_checked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="The date we last checked if the org had completed activation for the product.",
    )

    class Meta:
        unique_together = ["team", "product_type"]

    def __str__(self):
        return f"{self.team.name} - {self.product_type}"

    def has_activated_data_warehouse(self) -> bool:
        insights = Insight.objects.filter(
            team__project_id=self.team.project_id,
            created_at__gte=datetime(2024, 6, 1, tzinfo=UTC),
            query__kind="DataVisualizationNode",
        )

        excluded_tables = ["events", "persons", "sessions", "person_distinct_ids"]
        for insight in insights:
            if insight.query and insight.query.get("source", {}).get("query"):
                query_text = insight.query["source"]["query"].lower()
                # Check if query doesn't contain any of the excluded tables after 'from'
                has_excluded_table = any(f"from {table}" in query_text.replace("\\", "") for table in excluded_tables)
                if not has_excluded_table:
                    return True

        return False

    def has_activated_experiments(self) -> bool:
        # the team has any launched experiments
        return Experiment.objects.filter(
            team=self.team, status__in=[Experiment.Status.RUNNING, Experiment.Status.STOPPED]
        ).exists()

    def has_activated_error_tracking(self) -> bool:
        # the team has resolved any issues
        return ErrorTrackingIssue.objects.filter(team=self.team, status=ErrorTrackingIssue.Status.RESOLVED).exists()

    def has_activated_surveys(self) -> bool:
        return Survey.objects.filter(team__project_id=self.team.project_id, start_date__isnull=False).exists()

    def has_activated_feature_flags(self) -> bool:
        # Get feature flags that have at least one filter group, excluding ones used by experiments, surveys, and product tours
        experiment_flags = Experiment.objects.filter(team=self.team).values_list("feature_flag_id", flat=True)
        survey_flags = Survey.objects.filter(team=self.team).values_list("targeting_flag_id", flat=True)
        product_tour_flags = ProductTour.all_objects.filter(team=self.team).values_list(
            "internal_targeting_flag_id", flat=True
        )

        feature_flags = (
            FeatureFlag.objects.filter(
                team=self.team,
                filters__groups__0__properties__isnull=False,
            )
            .exclude(id__in=experiment_flags)
            .exclude(id__in=survey_flags)
            .exclude(id__in=product_tour_flags)
            .only("id", "filters")
        )

        # To activate we need at least 2 feature flags
        if feature_flags.count() < 2:
            return False

        # To activate we need at least 2 filter groups across all flags
        total_groups = 0
        for flag in feature_flags:
            total_groups += len(flag.filters.get("groups", []))

        return total_groups >= 2

    def has_activated_session_replay(self) -> bool:
        has_viewed_five_recordings = SessionRecordingViewed.objects.filter(team=self.team).count() >= 5

        intent = ProductIntent.objects.filter(
            team=self.team,
            product_type="session_replay",
        ).first()

        if not intent:
            return False

        contexts = intent.contexts or {}

        set_filters_count = contexts.get("session_replay_set_filters", 0)

        if set_filters_count >= 1 and has_viewed_five_recordings:
            return True

        return False

    def has_activated_product_analytics(self) -> bool:
        insights = Insight.objects.filter(team=self.team, created_by__isnull=False)

        if insights.count() < 3:
            return False

        dashboards = Dashboard.objects.filter(team=self.team, created_by__isnull=False)

        if dashboards.count() < 1:
            return False

        return self.team.ingested_event

    def has_activated_llm_analytics(self) -> bool:
        has_ai_generation = EventDefinition.objects.filter(team=self.team, name="$ai_generation").exists()
        if not has_ai_generation:
            return False

        intent = ProductIntent.objects.filter(
            team=self.team,
            product_type="llm_analytics",
        ).first()

        if not intent:
            return False

        contexts = intent.contexts or {}

        # Activated when the user has engaged with the dashboard (15s dwell) or viewed a trace
        return contexts.get("llm_analytics_viewed", 0) >= 1 or contexts.get("llm_analytics_trace_viewed", 0) >= 1

    def has_activated_workflows(self) -> bool:
        # At least one workflow needs to be active (not just drafted)
        return HogFlow.objects.filter(team=self.team, status=HogFlow.State.ACTIVE).exists()

    def check_and_update_activation(self, skip_reporting: bool = False) -> bool:
        # If the intent is already activated, we don't need to check again
        if self.activated_at:
            return True

        # Update the last activation check time
        self.activation_last_checked_at = datetime.now(tz=UTC)
        self.save()

        activation_checks = {
            "data_warehouse": self.has_activated_data_warehouse,
            "experiments": self.has_activated_experiments,
            "feature_flags": self.has_activated_feature_flags,
            "session_replay": self.has_activated_session_replay,
            "error_tracking": self.has_activated_error_tracking,
            "product_analytics": self.has_activated_product_analytics,
            "surveys": self.has_activated_surveys,
            "llm_analytics": self.has_activated_llm_analytics,
            "workflows": self.has_activated_workflows,
        }

        if self.product_type in activation_checks and activation_checks[self.product_type]():
            self.activated_at = datetime.now(tz=UTC)
            self.save()
            if not skip_reporting:
                self.report_activation(self.product_type)
            return True

        return False

    def report_activation(self, product_key: str) -> None:
        from posthog.event_usage import report_team_action

        report_team_action(
            self.team,
            "product intent marked activated",
            {
                "product_key": product_key,
                "intent_created_at": self.created_at,
                "intent_updated_at": self.updated_at,
                "realm": get_instance_realm(),
            },
        )

    @staticmethod
    def register(
        team: Team,
        product_type: ProductKey,
        context: Optional[ProductIntentContext],
        user: User,
        metadata: Optional[dict] = None,
        is_onboarding: bool = False,
    ) -> "ProductIntent":
        from posthog.event_usage import report_user_action
        from posthog.models.file_system.user_product_list import UserProductList

        product_intent, created = ProductIntent.objects.get_or_create(team=team, product_type=product_type)

        contexts = product_intent.contexts or {}

        product_intent.contexts = {
            **contexts,
            context: contexts.get(context, 0) + 1,
        }

        if is_onboarding:
            product_intent.onboarding_completed_at = datetime.now(tz=UTC)

        product_intent.save()

        if created:
            # For new intents, check activation immediately but skip reporting
            product_intent.check_and_update_activation(skip_reporting=True)
        else:
            if not product_intent.activated_at:
                product_intent.check_and_update_activation()
            product_intent.updated_at = datetime.now(tz=UTC)
            product_intent.save()

        if isinstance(user, User):
            report_user_action(
                user,
                "user showed product intent",
                {
                    **(metadata or {}),
                    "product_key": product_type,
                    "$set_once": {"first_onboarding_product_selected": product_type} if is_onboarding else {},
                    "intent_context": context,
                    "is_first_intent_for_product": created,
                    "intent_created_at": product_intent.created_at,
                    "intent_updated_at": product_intent.updated_at,
                    "realm": get_instance_realm(),
                },
                team=team,
            )

            try:
                UserProductList.create_from_product_intent(product_intent, user)
            except Exception as e:
                capture_exception(
                    e, additional_properties={"product_type": product_type, "context": context, "user_id": user.id}
                )

        return product_intent


@shared_task(ignore_result=True)
@skip_team_scope_audit
def calculate_product_activation(team_id: int, only_calc_if_days_since_last_checked: int = 1) -> None:
    """
    Calculate product activation for a team.
    Only calculate if it's been more than `only_calc_if_days_since_last_checked` days since the last activation check.
    """
    team = Team.objects.get(id=team_id)
    product_intents = ProductIntent.objects.filter(team=team)
    for product_intent in product_intents:
        if product_intent.activated_at:
            continue
        if (
            product_intent.activation_last_checked_at
            and (datetime.now(tz=UTC) - product_intent.activation_last_checked_at).days
            <= only_calc_if_days_since_last_checked
        ):
            continue
        product_intent.check_and_update_activation()


# Intentionally matches the default of `only_calc_if_days_since_last_checked=1`
# in `calculate_product_activation` above. The two together define the
# activation re-check cadence — tune them together.
PRODUCT_ACTIVATION_DEBOUNCE_TTL_SECONDS = 24 * 60 * 60


def enqueue_product_activation_calc_debounced(team_id: int) -> bool:
    """Enqueue `calculate_product_activation` for this team at most once per 24h.

    The Celery task itself already short-circuits each not-yet-activated intent with
    `only_calc_if_days_since_last_checked=1`, so enqueueing on every page render was
    wasted broker traffic that the worker would no-op. This guard skips the enqueue
    when we've already done it for this team within the debounce window.

    Failure mode: if the cache backend errors (e.g. Redis blip), fail open and
    enqueue anyway — better to take the broker round-trip than to 500 the team
    list endpoint. The inner task's per-intent short-circuit limits the cost.

    Best-effort: the debounce key is set unconditionally before enqueueing, so a
    Celery enqueue or worker failure leaves the team debounced for up to 24h. The
    primary activation path is `ProductIntent.register()` which calls
    `check_and_update_activation()` synchronously; this helper exists only for the
    periodic re-check of criteria that became met after registration.

    Returns True when the task was enqueued, False when the call was debounced.
    """
    debounce_key = f"product_activation_enqueued:{team_id}"
    try:
        was_added = cache.add(debounce_key, "1", timeout=PRODUCT_ACTIVATION_DEBOUNCE_TTL_SECONDS)
    except Exception as e:
        # Cache error must not block the enqueue path; fall through to .delay().
        # Log + capture so a chronic Redis problem still surfaces in monitoring
        # rather than silently degrading to "every render enqueues" (which would
        # otherwise look identical to working code).
        logger.warning("product_activation_debounce_cache_failure", team_id=team_id, exc_info=True)
        capture_exception(e)
        was_added = True
    if was_added:
        calculate_product_activation.delay(team_id, only_calc_if_days_since_last_checked=1)
        return True
    return False


PRODUCT_INTENTS_CACHE_TTL_SECONDS = 60 * 60


def _team_product_intents_cache_key(team_id: int) -> str:
    return f"team_serializer:product_intents:{team_id}"


def _fetch_product_intents(team_id: int) -> list[dict[str, Any]]:
    return list(
        ProductIntent.objects.filter(team_id=team_id).values(
            "product_type", "created_at", "onboarding_completed_at", "updated_at"
        )
    )


def cached_product_intents_for_team(team_id: int) -> list[dict[str, Any]]:
    """Per-team cache for the product_intents response on the team serializer.

    Production traces showed `team_serializer.product_intents` taking up to 532ms
    on the home view. The query result changes only when a ProductIntent row writes
    or deletes; the post_save / post_delete receivers below invalidate immediately.
    A 1h TTL caps staleness for any path that bypasses the ORM signals.
    """
    cache_key = _team_product_intents_cache_key(team_id)
    cached = get_safe_cache(cache_key)
    if cached is not None:
        return cached
    result = _fetch_product_intents(team_id)
    safe_cache_set(cache_key, result, timeout=PRODUCT_INTENTS_CACHE_TTL_SECONDS)
    return result


def _invalidate_product_intents_cache(team_id: int) -> None:
    safe_cache_delete(_team_product_intents_cache_key(team_id))
    transaction.on_commit(lambda: safe_cache_delete(_team_product_intents_cache_key(team_id)))


@receiver(pre_save, sender=ProductIntent)
def _capture_original_team_id(sender: type[ProductIntent], instance: ProductIntent, **kwargs: Any) -> None:
    # Stash the persisted team_id before save so post_save can invalidate the previous
    # team's cache when an intent is reassigned (instance.team_id != original).
    # For new rows the filter returns None (no row yet), which is the right value to stash.
    try:
        instance._original_team_id = (  # type: ignore[attr-defined]
            ProductIntent.objects.filter(pk=instance.pk).values_list("team_id", flat=True).first()
        )
    except Exception:
        instance._original_team_id = None  # type: ignore[attr-defined]


@receiver(post_save, sender=ProductIntent)
def _invalidate_product_intents_on_save(sender: type[ProductIntent], instance: ProductIntent, **kwargs: Any) -> None:
    _invalidate_product_intents_cache(instance.team_id)
    original_team_id = getattr(instance, "_original_team_id", None)
    if original_team_id is not None and original_team_id != instance.team_id:
        _invalidate_product_intents_cache(original_team_id)


@receiver(post_delete, sender=ProductIntent)
def _invalidate_product_intents_on_delete(sender: type[ProductIntent], instance: ProductIntent, **kwargs: Any) -> None:
    _invalidate_product_intents_cache(instance.team_id)
