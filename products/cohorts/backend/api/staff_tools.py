from typing import Any, cast

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema_serializer
from rest_framework import request, response, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from posthog.api.fields import RepeatedOrCommaSeparatedListField
from posthog.api.mixins import validated_request
from posthog.exceptions_capture import capture_exception
from posthog.helpers.impersonation import is_impersonated
from posthog.models.user import User
from posthog.permissions import IsStaffUser
from posthog.tasks.calculate_cohort import (
    get_stuck_cohort_calculation_candidates_queryset,
    increment_version_and_enqueue_calculate_cohort,
)

from products.cohorts.backend.models.cohort import Cohort

logger = structlog.get_logger(__name__)

MAX_COHORTS_PER_LOOKUP = 50
# Recalculating a cohort fans out into its full dependency chain of ClickHouse calculations,
# so the batch cap is much lower than for the lookup.
MAX_COHORTS_PER_RECALCULATE = 10
MAX_STUCK_COHORTS_LISTED = 100

SKIP_REASON_DELETED = "Cohort is deleted."
SKIP_REASON_STATIC = "Static cohorts are populated once from their source; recalculation is not supported."


def _cohort_ids_field(help_text: str, *, max_length: int) -> serializers.ListField:
    return RepeatedOrCommaSeparatedListField(
        child=serializers.IntegerField(), min_length=1, max_length=max_length, help_text=help_text
    )


class StaffCohortLookupQuerySerializer(serializers.Serializer):
    cohort_ids = _cohort_ids_field(
        f"Cohort ids to look up (max {MAX_COHORTS_PER_LOOKUP} per request). Repeat the param "
        "(?cohort_ids=1&cohort_ids=2) or pass one comma-separated value (?cohort_ids=1,2).",
        max_length=MAX_COHORTS_PER_LOOKUP,
    )


class StaffCohortSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="Cohort id.")
    name = serializers.CharField(allow_null=True, help_text="Cohort name.")
    team_id = serializers.IntegerField(help_text="Id of the team the cohort belongs to.")
    team_name = serializers.CharField(source="team.name", help_text="Name of the team the cohort belongs to.")
    project_id = serializers.IntegerField(
        source="team.project_id",
        help_text="Project id the cohort's team belongs to, for building /project/<id>/cohorts/<id> links.",
    )
    deleted = serializers.BooleanField(help_text="Whether the cohort is soft-deleted.")
    is_static = serializers.BooleanField(
        help_text="Whether the cohort is static (populated once from a source rather than recalculated)."
    )
    is_calculating = serializers.BooleanField(help_text="Whether a calculation is currently marked as in flight.")
    last_calculation = serializers.DateTimeField(
        allow_null=True, help_text="When the last calculation completed, or null if never calculated."
    )
    last_calculation_duration_ms = serializers.IntegerField(
        allow_null=True, help_text="Duration of the last completed calculation in milliseconds."
    )
    errors_calculating = serializers.IntegerField(
        help_text="Consecutive calculation failures; above 20 the cohort is excluded from periodic recalculation."
    )
    last_error_at = serializers.DateTimeField(
        allow_null=True, help_text="When the last calculation error was recorded."
    )
    version = serializers.IntegerField(allow_null=True, help_text="Version of the last completed calculation.")
    pending_version = serializers.IntegerField(
        allow_null=True,
        help_text="Version most recently requested; greater than `version` while a calculation is pending or stuck.",
    )
    count = serializers.IntegerField(
        allow_null=True, help_text="Number of persons in the cohort as of the last completed calculation."
    )
    created_at = serializers.DateTimeField(allow_null=True, help_text="When the cohort was created.")


@extend_schema_serializer(many=False)
class StaffCohortLookupResponseSerializer(serializers.Serializer):
    results = StaffCohortSerializer(many=True, help_text="Requested cohorts, in request order.")
    not_found_cohort_ids = serializers.ListField(
        child=serializers.IntegerField(), help_text="Requested cohort ids that do not exist."
    )


@extend_schema_serializer(many=False)
class StaffStuckCohortsResponseSerializer(serializers.Serializer):
    results = StaffCohortSerializer(
        many=True,
        help_text=f"Stuck cohorts, oldest last_calculation first (max {MAX_STUCK_COHORTS_LISTED}).",
    )
    total_count = serializers.IntegerField(help_text="Total number of stuck cohorts instance-wide.")


class StaffCohortRecalculateSerializer(serializers.Serializer):
    cohort_ids = _cohort_ids_field(
        f"Cohort ids to force-recalculate (max {MAX_COHORTS_PER_RECALCULATE} per request).",
        max_length=MAX_COHORTS_PER_RECALCULATE,
    )


class StaffCohortSkippedSerializer(serializers.Serializer):
    cohort_id = serializers.IntegerField(help_text="Cohort id that was skipped.")
    reason = serializers.CharField(help_text="Why the cohort was not enqueued for recalculation.")


class StaffCohortFailedSerializer(serializers.Serializer):
    cohort_id = serializers.IntegerField(help_text="Cohort id that raised while being enqueued.")
    error = serializers.CharField(help_text="Error message from the failed enqueue attempt.")


@extend_schema_serializer(many=False)
class StaffCohortRecalculateResponseSerializer(serializers.Serializer):
    queued_cohort_ids = serializers.ListField(
        child=serializers.IntegerField(),
        help_text="Cohort ids for which a recalculation was enqueued (including their dependency chains).",
    )
    partial_cohort_ids = serializers.ListField(
        child=serializers.IntegerField(),
        help_text="Subset of queued_cohort_ids whose dependency chain failed to resolve, so only the cohort "
        "itself (not its dependents/dependencies) was enqueued. Those related cohorts are still stale; "
        "re-request recalculation for them explicitly once the dependency issue is fixed.",
    )
    failed_cohort_ids = StaffCohortFailedSerializer(
        many=True,
        help_text="Cohort ids that raised while being enqueued and were not queued at all. Cohorts listed "
        "elsewhere in this response already had their enqueue attempted; retry only these ids rather than "
        "the whole batch.",
    )
    skipped = StaffCohortSkippedSerializer(
        many=True, help_text="Cohorts that exist but were not enqueued, with the reason."
    )
    not_found_cohort_ids = serializers.ListField(
        child=serializers.IntegerField(), help_text="Requested cohort ids that do not exist."
    )


class CohortsStaffToolsViewSet(viewsets.ViewSet):
    """
    Staff-only, unscoped cohort calculation tooling.

    Replaces the prod-shell runbook for stuck cohort calculations: look up any team's cohort by
    id, list cohorts whose calculation is stuck, and force-recalculate by bumping
    pending_version and enqueueing through the same task path organic saves use.

    Registered on the root router so it is not team-nested; staff act on cohorts in teams they
    do not belong to. Cohort.objects is not fail-closed today (the model is on the scoping
    baseline) — if Cohort migrates to a fail-closed manager, these cross-team queries must
    switch to the explicit unscoped escape hatch.
    """

    # Not part of the public API scope model: access is gated entirely by IsStaffUser below,
    # not by a personal-API-key scope, so this stays out of the public OpenAPI/generated-client
    # surface (see posthog/api/documentation.py's INTERNAL handling).
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated, IsStaffUser]

    @validated_request(
        query_serializer=StaffCohortLookupQuerySerializer,
        responses={200: OpenApiResponse(response=StaffCohortLookupResponseSerializer)},
    )
    def list(self, request: request.Request, **kwargs: Any) -> response.Response:
        # Dedupe (preserving order) so a caller passing the same id twice doesn't get duplicate
        # rows in `results`.
        cohort_ids: list[int] = list(dict.fromkeys(request.validated_query_data["cohort_ids"]))
        # No deleted=False filter: staff need to see a deleted cohort's state to explain why it
        # stopped calculating.
        # Staff-only, cross-team by design: see class docstring.
        # nosemgrep: idor-lookup-without-team
        cohorts = Cohort.objects.select_related("team").filter(id__in=cohort_ids)
        cohorts_by_id = {cohort.id: cohort for cohort in cohorts}
        found = [cohorts_by_id[cohort_id] for cohort_id in cohort_ids if cohort_id in cohorts_by_id]
        not_found_ids = [cohort_id for cohort_id in cohort_ids if cohort_id not in cohorts_by_id]

        return response.Response(
            StaffCohortLookupResponseSerializer({"results": found, "not_found_cohort_ids": not_found_ids}).data
        )

    @validated_request(responses={200: OpenApiResponse(response=StaffStuckCohortsResponseSerializer)})
    @action(methods=["GET"], detail=False)
    def stuck(self, request: request.Request, **kwargs: Any) -> response.Response:
        # Same definition of "stuck" the periodic reset task uses: is_calculating for over an
        # hour past the last completed calculation, dynamic cohorts only.
        queryset = get_stuck_cohort_calculation_candidates_queryset()
        total_count = queryset.count()
        stuck = queryset.select_related("team").order_by("last_calculation")[:MAX_STUCK_COHORTS_LISTED]

        return response.Response(
            StaffStuckCohortsResponseSerializer({"results": list(stuck), "total_count": total_count}).data
        )

    @validated_request(
        request_serializer=StaffCohortRecalculateSerializer,
        responses={202: OpenApiResponse(response=StaffCohortRecalculateResponseSerializer)},
    )
    @action(methods=["POST"], detail=False)
    def recalculate(self, request: request.Request, **kwargs: Any) -> response.Response:
        cohort_ids: list[int] = list(dict.fromkeys(request.validated_data["cohort_ids"]))
        # Staff-only, cross-team by design: see class docstring.
        # nosemgrep: idor-lookup-without-team, idor-taint-user-input-to-model-get
        cohorts_by_id = {cohort.id: cohort for cohort in Cohort.objects.filter(id__in=cohort_ids)}

        queued_ids: list[int] = []
        partial_ids: list[int] = []
        failed: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        not_found_ids: list[int] = []
        for cohort_id in cohort_ids:
            cohort = cohorts_by_id.get(cohort_id)
            if cohort is None:
                not_found_ids.append(cohort_id)
            elif cohort.deleted:
                skipped.append({"cohort_id": cohort_id, "reason": SKIP_REASON_DELETED})
            elif cohort.is_static:
                skipped.append({"cohort_id": cohort_id, "reason": SKIP_REASON_STATIC})
            else:
                # Deliberately no is_calculating guard: stuck cohorts are the whole point, and
                # the pending_version bump supersedes any stale in-flight run.
                # Caught per-cohort so one bad cohort doesn't 500 the whole batch and hide which
                # of the earlier cohorts in the loop already had their version bumped and task
                # enqueued (those must not be retried; only failed_cohort_ids should be).
                try:
                    # IsAuthenticated + IsStaffUser guarantee a real User here.
                    fully_resolved = increment_version_and_enqueue_calculate_cohort(
                        cohort, initiating_user=cast(User, request.user)
                    )
                except Exception as e:
                    logger.exception("cohorts_staff_recalculate_enqueue_failed", cohort_id=cohort_id, error=str(e))
                    capture_exception(e)
                    failed.append({"cohort_id": cohort_id, "error": str(e)})
                else:
                    queued_ids.append(cohort_id)
                    if not fully_resolved:
                        partial_ids.append(cohort_id)

        logger.info(
            "cohorts_staff_recalculate",
            staff_user_id=request.user.id,
            was_impersonated=is_impersonated(request),
            queued_cohort_ids=queued_ids,
            partial_cohort_ids=partial_ids,
            failed_cohort_ids=[f["cohort_id"] for f in failed],
            skipped=skipped,
            not_found_cohort_ids=not_found_ids,
        )

        return response.Response(
            {
                "queued_cohort_ids": queued_ids,
                "partial_cohort_ids": partial_ids,
                "failed_cohort_ids": failed,
                "skipped": skipped,
                "not_found_cohort_ids": not_found_ids,
            },
            status=status.HTTP_202_ACCEPTED,
        )
