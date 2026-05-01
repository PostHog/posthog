import json
from dataclasses import asdict
from typing import Any, cast

from django.conf import settings

import structlog
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team
from posthog.models.user import User
from posthog.redis import get_client

from products.growth.backend.constants import SDK_TYPES, SdkVersionEntry, github_sdk_versions_key, team_sdk_versions_key
from products.growth.backend.sdk_health import SdkHealthReport, compute_sdk_health

# NOTE: products.growth.backend.team_sdk_versions is imported lazily inside get_team_data
# below. It transitively imports from posthog/dags which calls django.setup() — that
# causes a RuntimeError("populate() isn't reentrant") if we let it happen at module
# import time from posthog/api/__init__.py. SDK_TYPES used to trigger the same chain
# when it lived in products.growth.dags.github_sdk_versions; it now lives in
# products.growth.backend.constants (which has no Django side effects) and can be a
# top-level import.

logger = structlog.get_logger(__name__)


# --- DRF serializers (drive OpenAPI → MCP tool descriptions) ---------------


class SdkReleaseAssessmentSerializer(serializers.Serializer):
    version = serializers.CharField(help_text="In-use SDK version string, e.g. '1.298.0'.")
    count = serializers.IntegerField(help_text="Number of events captured with this version in the last 7 days.")
    max_timestamp = serializers.CharField(
        help_text="Timestamp of the most recent event seen for this version (ISO 8601)."
    )
    release_date = serializers.CharField(
        allow_null=True,
        help_text="When this version was published on GitHub (ISO 8601), or null if unknown.",
    )
    days_since_release = serializers.IntegerField(
        allow_null=True, help_text="Days since this version was released, or null if unknown."
    )
    released_ago = serializers.CharField(
        allow_null=True,
        help_text="Human-readable relative release age matching the UI (e.g. '5 months ago'). Null when release_date is unknown.",
    )
    is_outdated = serializers.BooleanField(
        help_text="True when this version is flagged as outdated by smart-semver rules."
    )
    is_old = serializers.BooleanField(
        help_text="True when this version is flagged as old by age alone (separate from semver rules)."
    )
    needs_updating = serializers.BooleanField(help_text="True if is_outdated OR is_old.")
    is_current_or_newer = serializers.BooleanField(
        help_text="True when this version equals or exceeds the latest known published version."
    )
    status_reason = serializers.CharField(
        help_text=(
            "Per-version badge tooltip text matching the SDK Doctor UI exactly. Quote verbatim when "
            "reporting to users. Varies by state: 'Released X ago. Upgrade recommended.' for outdated "
            "versions, 'You have the latest available. Click Releases above to check for any since.' "
            "for current versions, or 'Released X ago. Upgrading is a good idea, but it's not urgent "
            "yet.' for recent-but-behind versions."
        ),
    )
    sql_query = serializers.CharField(
        help_text=(
            "SQL SELECT statement for drilling into events for this SDK version over the last 7 days. "
            "Suitable to pass to the execute-sql tool or to display as a copy-paste snippet."
        ),
    )
    activity_page_url = serializers.CharField(
        help_text=(
            "Relative URL path (starting with /project/{id}/) for the Activity > Explore page "
            "pre-filtered to events captured with this lib and lib_version over the last 7 days. "
            "Combine with the user's PostHog host (e.g. us.posthog.com) for a clickable link."
        ),
    )


class OutdatedTrafficAlertSerializer(serializers.Serializer):
    version = serializers.CharField(help_text="Outdated version handling significant traffic.")
    threshold_percent = serializers.FloatField(
        help_text="Traffic-percentage threshold that triggered the alert (10% for most SDKs, 20% for web)."
    )


class SdkAssessmentSerializer(serializers.Serializer):
    lib = serializers.CharField(
        help_text="SDK identifier, e.g. 'web', 'posthog-python', 'posthog-node', 'posthog-ios'."
    )
    readable_name = serializers.CharField(
        help_text="Human-readable SDK name matching the SDK Doctor UI (e.g. 'Python', 'Node.js', 'Web', 'iOS')."
    )
    latest_version = serializers.CharField(help_text="Most recent published version of this SDK.")
    needs_updating = serializers.BooleanField(help_text="True if this SDK needs attention (is_outdated OR is_old).")
    is_outdated = serializers.BooleanField(help_text="True if the primary in-use version is flagged as outdated.")
    is_old = serializers.BooleanField(help_text="True if the primary in-use version is flagged as old by age alone.")
    severity = serializers.ChoiceField(
        choices=["none", "warning", "danger"],
        help_text="UI severity badge — 'none' when healthy, 'warning' when outdated, 'danger' when the majority of team SDKs are outdated.",
    )
    reason = serializers.CharField(
        help_text=(
            "Per-SDK programmatic summary (used for ranking/filtering). For user-facing copy, prefer "
            "releases[].status_reason (badge tooltip) and banners (top-level alert text) — those match "
            "the UI exactly."
        ),
    )
    banners = serializers.ListField(
        child=serializers.CharField(),
        help_text=(
            "Top-level alert sentences matching the SDK Doctor UI's 'Time for an update!' banner — "
            "one per outdated version with significant traffic. Quote verbatim when surfacing the "
            "headline to users."
        ),
    )
    releases = SdkReleaseAssessmentSerializer(
        many=True, help_text="Per-version assessment for all versions seen in the last 7 days."
    )
    outdated_traffic_alerts = OutdatedTrafficAlertSerializer(
        many=True,
        help_text="Outdated versions that handle a significant share of traffic (above the threshold). Not populated for mobile SDKs.",
    )


class SdkHealthReportSerializer(serializers.Serializer):
    overall_health = serializers.ChoiceField(
        choices=["healthy", "needs_attention"],
        help_text="'healthy' when no SDKs need updating, 'needs_attention' otherwise.",
    )
    health = serializers.ChoiceField(
        choices=["success", "warning", "danger"],
        help_text="UI-level status — 'success' when healthy, 'warning' when some SDKs are outdated, 'danger' when the majority are outdated.",
    )
    needs_updating_count = serializers.IntegerField(help_text="Number of SDKs that need updating.")
    team_sdk_count = serializers.IntegerField(
        help_text="Number of distinct PostHog SDKs the project is actively using."
    )
    sdks = SdkAssessmentSerializer(many=True, help_text="Per-SDK health assessments.")


# --- ViewSet (MCP-accessible, project-scoped) ------------------------------


@extend_schema(tags=["sdk_doctor"])
class SdkDoctorViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Project-scoped SDK Doctor report for MCP and agent consumption."""

    scope_object = "project"

    @extend_schema(
        summary="Get SDK health report for a project",
        description=(
            "Returns a pre-digested health assessment of the PostHog SDKs the project is using. "
            "Covers which SDKs are current vs outdated (smart-semver rules with grace periods "
            "and traffic-percentage thresholds), per-version breakdown, and a human-readable "
            "reason for each assessment. Use this to diagnose SDK version issues, surface upgrade "
            "recommendations, or check overall SDK health."
        ),
        responses={200: SdkHealthReportSerializer},
        parameters=[
            OpenApiParameter(
                name="force_refresh",
                type=bool,
                required=False,
                description=(
                    "When true, bypasses the Redis cache and re-queries ClickHouse for SDK usage. "
                    "Use sparingly — data is refreshed every 12 hours by a background job."
                ),
            ),
        ],
    )
    @action(detail=False, methods=["get"], url_path="report", required_scopes=["project:read"])
    def report(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        force_refresh = request.GET.get("force_refresh", "").lower() == "true"

        team_data = get_team_data(self.team_id, force_refresh)
        sdk_data = get_github_sdk_data()

        if not team_data or not sdk_data:
            empty = SdkHealthReport(
                overall_health="healthy",
                needs_updating_count=0,
                team_sdk_count=0,
                health="success",
                sdks=[],
            )
            return Response(SdkHealthReportSerializer(asdict(empty)).data)

        combined: dict[str, dict[str, Any]] = {}
        for lib, entries in team_data.items():
            sdk_for_lib = sdk_data.get(lib, {})
            latest_version = sdk_for_lib.get("latestVersion")
            combined[lib] = {
                "latest_version": latest_version,
                "usage": [
                    {
                        **entry,
                        "is_latest": entry["lib_version"] == latest_version,
                        "release_date": sdk_for_lib.get("releaseDates", {}).get(entry["lib_version"]),
                    }
                    for entry in entries
                ],
            }

        report = compute_sdk_health(combined, project_id=self.team_id)
        return Response(SdkHealthReportSerializer(asdict(report)).data)


# --- Existing flat endpoint (unchanged) ------------------------------------


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sdk_doctor(request: Request) -> Response:
    """
    Serve team SDK versions. Data is cached by the Temporal sdk_outdated health check.
    Supports force_refresh=true for on-demand detection.
    """
    user = cast(User, request.user)

    team_id = cast(Team, user.team).id
    raw_force_refresh = request.GET.get("force_refresh", "")
    force_refresh = raw_force_refresh.lower() == "true"

    team_data = get_team_data(team_id, force_refresh)
    if not team_data:
        if settings.DEBUG:  # Running locally, usually doesn't have anything in the cache, just return empty
            logger.info(
                "sdk_doctor_no_local_data",
                team_id=team_id,
                detail="no data received from ClickHouse, returning empty response",
            )
            return Response({}, status=200)

        return Response({"error": "Failed to get SDK versions. Please try again later."}, status=500)

    sdk_data = get_github_sdk_data()
    if not sdk_data:
        return Response({"error": "Failed to get GitHub SDK data. Please try again later."}, status=500)

    # Combine the team data with SDK data by including the date for each release
    # on the team data alongside whether it's the latest or not
    combined_data = {}
    for lib, entries in team_data.items():
        sdk_data_for_lib = sdk_data[lib]
        combined_data[lib] = {
            "latest_version": sdk_data_for_lib["latestVersion"],
            "usage": [
                {
                    **entry,
                    "is_latest": entry["lib_version"] == sdk_data_for_lib["latestVersion"],
                    "release_date": sdk_data_for_lib["releaseDates"].get(entry["lib_version"], None),
                }
                for entry in entries
            ],
        }

    return Response(combined_data, status=200)


def get_team_data(team_id: int, force_refresh: bool) -> dict[str, list[SdkVersionEntry]] | None:
    from products.growth.backend.team_sdk_versions import get_and_cache_team_sdk_versions

    redis_client = get_client()
    cache_key = team_sdk_versions_key(team_id)

    if not force_refresh:
        cached_data = redis_client.get(cache_key)
        if cached_data:
            try:
                sdk_versions = json.loads(
                    cached_data.decode("utf-8") if isinstance(cached_data, bytes) else cached_data
                )
                logger.info("sdk_doctor_team_cache_hit", team_id=team_id)
                return sdk_versions
            except (json.JSONDecodeError, AttributeError) as e:
                logger.warning("sdk_doctor_team_cache_corrupted", team_id=team_id, error=str(e))
                capture_exception(e)
    else:
        logger.info("sdk_doctor_team_force_refresh", team_id=team_id)

    logger.info("sdk_doctor_team_cache_miss", team_id=team_id)
    try:
        sdk_versions = get_and_cache_team_sdk_versions(team_id, redis_client)
        if sdk_versions is not None:
            logger.info("sdk_doctor_team_cache_populated", team_id=team_id)
            return sdk_versions
        else:
            logger.error("sdk_doctor_team_clickhouse_empty", team_id=team_id)
    except Exception as e:
        logger.exception("sdk_doctor_team_fetch_failed", team_id=team_id)
        capture_exception(e)

    return None


def get_github_sdk_data() -> dict[str, Any]:
    redis_client = get_client()

    data: dict[str, Any] = {}
    for sdk_type in SDK_TYPES:
        cache_key = github_sdk_versions_key(sdk_type)
        cached_data = redis_client.get(cache_key)
        if cached_data:
            try:
                parsed = json.loads(cached_data.decode("utf-8") if isinstance(cached_data, bytes) else cached_data)
                data[sdk_type] = parsed
            except (json.JSONDecodeError, AttributeError) as e:
                logger.warning("sdk_doctor_github_cache_corrupted", sdk_type=sdk_type, error=str(e))
                capture_exception(e, {"sdk_type": sdk_type, "cache_key": cache_key})
        else:
            logger.warning("sdk_doctor_github_cache_miss", sdk_type=sdk_type)

    return data
