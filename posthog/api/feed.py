from datetime import timedelta
from typing import Any

from django.utils import timezone

from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.client import sync_execute
from posthog.models import Dashboard
from posthog.models.event_definition import EventDefinition
from posthog.models.experiment import Experiment
from posthog.models.feature_flag import FeatureFlag
from posthog.models.surveys.survey import Survey
from posthog.session_recordings.models.session_recording import ttl_days
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.temporal.weekly_digest.queries import (
    query_experiments_completed,
    query_experiments_launched,
    query_new_dashboards,
    query_new_event_definitions,
    query_new_feature_flags,
    query_saved_filters,
    query_surveys_launched,
)

from products.data_warehouse.backend.models.external_data_source import ExternalDataSource


class FeedItemSerializer(serializers.Serializer):
    id = serializers.CharField()  # Can be int or UUID, so use CharField
    type = serializers.CharField()
    name = serializers.CharField()
    created_at = serializers.DateTimeField(required=False)
    description = serializers.CharField(required=False, allow_null=True)
    created_by = serializers.CharField(required=False, allow_null=True)
    additional_data = serializers.JSONField(required=False)


class FeedViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"

    @action(detail=False, methods=["GET"])
    def recent_updates(self, request, **kwargs):
        """
        Get recent updates for the feed page, based on weekly digest data sources.
        """
        team = self.team
        days = int(request.query_params.get("days", 7))
        period_start = timezone.now() - timedelta(days=days)
        period_end = timezone.now()

        # Fetch all the different types of updates
        feed_items: list[dict[str, Any]] = []

        # New dashboards
        dashboards = query_new_dashboards(period_start, period_end).filter(team_id=team.id)[:5]
        for dashboard in dashboards:
            dashboard_obj = Dashboard.objects.select_related("created_by").get(id=dashboard["id"])
            feed_items.append(
                {
                    "id": dashboard["id"],
                    "type": "dashboard",
                    "name": dashboard["name"],
                    "created_at": dashboard_obj.created_at,
                    "description": "New dashboard created",
                    "created_by": dashboard_obj.created_by.email if dashboard_obj.created_by else None,
                }
            )

        # New event definitions
        event_defs = query_new_event_definitions(period_start, period_end).filter(team_id=team.id)[:5]
        for event_def in event_defs:
            event_obj = EventDefinition.objects.get(id=event_def["id"])
            feed_items.append(
                {
                    "id": str(event_def["id"]),
                    "type": "event_definition",
                    "name": event_def["name"],
                    "created_at": event_obj.created_at,
                    "description": "New event definition",
                    "created_by": None,  # EventDefinition doesn't have created_by field
                }
            )

        # Experiments launched
        experiments_launched = query_experiments_launched(period_start, period_end).filter(team_id=team.id)[:5]
        for exp in experiments_launched:
            exp_obj = Experiment.objects.select_related("created_by").get(id=exp["id"])
            feed_items.append(
                {
                    "id": exp["id"],
                    "type": "experiment_launched",
                    "name": exp["name"],
                    "created_at": exp["start_date"],
                    "description": "Experiment launched",
                    "created_by": exp_obj.created_by.email if exp_obj.created_by else None,
                }
            )

        # Experiments completed
        experiments_completed = query_experiments_completed(period_start, period_end).filter(team_id=team.id)[:5]
        for exp in experiments_completed:
            exp_obj = Experiment.objects.select_related("created_by").get(id=exp["id"])
            feed_items.append(
                {
                    "id": exp["id"],
                    "type": "experiment_completed",
                    "name": exp["name"],
                    "created_at": exp["end_date"],
                    "description": "Experiment completed",
                    "created_by": exp_obj.created_by.email if exp_obj.created_by else None,
                    "additional_data": {"start_date": exp["start_date"]},
                }
            )

        # New feature flags
        feature_flags = query_new_feature_flags(period_start, period_end).filter(team_id=team.id)[:5]
        for flag in feature_flags:
            flag_obj = FeatureFlag.objects.select_related("created_by").get(id=flag["id"])
            feed_items.append(
                {
                    "id": flag["id"],
                    "type": "feature_flag",
                    "name": flag["name"],
                    "created_at": flag_obj.created_at,
                    "description": f"New feature flag: {flag['key']}",
                    "created_by": flag_obj.created_by.email if flag_obj.created_by else None,
                    "additional_data": {"key": flag["key"]},
                }
            )

        # New surveys
        surveys = query_surveys_launched(period_start, period_end).filter(team_id=team.id)[:5]
        for survey in surveys:
            survey_obj = Survey.objects.select_related("created_by").get(id=survey["id"])
            feed_items.append(
                {
                    "id": str(survey["id"]),
                    "type": "survey",
                    "name": survey["name"],
                    "created_at": survey["start_date"],
                    "description": survey.get("description", "New survey launched"),
                    "created_by": survey_obj.created_by.email if survey_obj.created_by else None,
                }
            )

        # Interesting saved filters (session recordings)
        saved_filters = query_saved_filters(period_start, period_end).filter(team_id=team.id, view_count__gt=0)[:5]
        for filter_item in saved_filters:
            feed_items.append(
                {
                    "id": filter_item["short_id"],
                    "type": "session_recording_playlist",
                    "name": filter_item["name"] or "Untitled playlist",
                    "created_at": period_end,  # Use end of period as fallback
                    "description": f"Viewed {filter_item['view_count']} times",
                    "additional_data": {"view_count": filter_item["view_count"]},
                }
            )

        # New external data sources
        external_data_sources = ExternalDataSource.objects.filter(
            team_id=team.id,
            created_at__gt=period_start,
            created_at__lte=period_end,
            deleted=False,
        ).values("id", "source_type", "created_at")[:5]
        for source in external_data_sources:
            feed_items.append(
                {
                    "id": source["id"],
                    "type": "external_data_source",
                    "name": f"{source['source_type']} data source",
                    "created_at": source["created_at"],
                    "description": "New data source connected",
                }
            )

        # Expiring recordings (upcoming/warning item)
        try:
            TTL_THRESHOLD = 10  # days
            ch_query = SessionReplayEvents.count_soon_to_expire_sessions_query(format="JSON")
            result = sync_execute(
                ch_query,
                {
                    "team_id": team.id,
                    "python_now": timezone.now(),
                    "ttl_days": ttl_days(team),
                    "ttl_threshold": TTL_THRESHOLD,
                },
            )
            if result and result[0] and result[0][0] > 0:
                recording_count = result[0][0]
                feed_items.append(
                    {
                        "id": "expiring-recordings",
                        "type": "expiring_recordings",
                        "name": f"{recording_count} recording{'s' if recording_count != 1 else ''} expiring soon",
                        "created_at": timezone.now(),
                        "description": f"{recording_count} recording{'s' if recording_count != 1 else ''} will be deleted within {TTL_THRESHOLD} days",
                        "additional_data": {"recording_count": recording_count, "ttl_threshold": TTL_THRESHOLD},
                    }
                )
        except Exception:
            # Silently fail if expiring recordings query fails
            pass

        # Sort all items by created_at (most recent first)
        feed_items.sort(key=lambda x: x.get("created_at", period_start), reverse=True)

        # Limit to top 50 items
        feed_items = feed_items[:50]

        serializer = FeedItemSerializer(feed_items, many=True)
        return Response({"results": serializer.data, "count": len(serializer.data)})
