from datetime import datetime

from django.db.models import Count, Q, QuerySet

from posthog.helpers.session_recording_playlist_templates import DEFAULT_PLAYLIST_NAMES
from posthog.models import Organization
from posthog.models.dashboard import Dashboard
from posthog.models.event_definition import EventDefinition
from posthog.models.experiment import Experiment
from posthog.models.feature_flag import FeatureFlag
from posthog.models.organization import OrganizationMembership
from posthog.models.surveys.survey import Survey
from posthog.models.team import Team
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.sync import database_sync_to_async

from products.data_warehouse.backend.models.external_data_source import ExternalDataSource


def query_teams_for_digest() -> QuerySet:
    return (
        Team.objects.select_related("organization")
        .exclude(Q(organization__for_internal_metrics=True) | Q(is_demo=True))
        .only(
            "id",
            "name",
            "organization__id",
            "organization__name",
            "organization__created_at",
            "organization__available_product_features",
        )
    )


def query_orgs_for_digest() -> QuerySet:
    return Organization.objects.exclude(Q(for_internal_metrics=True)).only("id", "name", "created_at")


def query_org_teams(organization: Organization) -> QuerySet:
    return Team.objects.only("id", "name").filter(organization=organization).exclude(is_demo=True)


def query_org_members(organization: Organization) -> QuerySet:
    return (
        OrganizationMembership.objects.filter(organization_id=organization.id)
        .select_related("user")
        .only("id", "user__distinct_id")
    )


def query_new_dashboards(period_start: datetime, period_end: datetime) -> QuerySet:
    return (
        Dashboard.objects.filter(created_at__gt=period_start, created_at__lte=period_end)
        .exclude(name__contains="Generated Dashboard")
        .values("team_id", "name", "id")
    )


def query_new_event_definitions(period_start: datetime, period_end: datetime) -> QuerySet:
    return EventDefinition.objects.filter(created_at__gt=period_start, created_at__lte=period_end).values(
        "team_id", "name", "id"
    )


def query_experiments_launched(period_start: datetime, period_end: datetime) -> QuerySet:
    return (
        Experiment.objects.filter(
            start_date__gt=period_start,
            start_date__lte=period_end,
        )
        .exclude(
            end_date__gt=period_start,
            end_date__lte=period_end,
        )
        .values("team_id", "name", "id", "start_date")
    )


def query_experiments_completed(period_start: datetime, period_end: datetime) -> QuerySet:
    return Experiment.objects.filter(end_date__gt=period_start, end_date__lte=period_end).values(
        "team_id", "name", "id", "start_date", "end_date"
    )


def query_new_external_data_sources(period_start: datetime, period_end: datetime) -> QuerySet:
    return ExternalDataSource.objects.filter(
        created_at__gt=period_start, created_at__lte=period_end, deleted=False
    ).values("team_id", "source_type", "id")


def query_surveys_launched(period_start: datetime, period_end: datetime) -> QuerySet:
    return Survey.objects.filter(start_date__gt=period_start, start_date__lte=period_end).values(
        "team_id", "name", "id", "description", "start_date"
    )


def query_new_feature_flags(period_start: datetime, period_end: datetime) -> QuerySet:
    return (
        FeatureFlag.objects.filter(
            created_at__gt=period_start,
            created_at__lte=period_end,
            deleted=False,
        )
        .exclude(name__contains="Feature Flag for Experiment")
        .exclude(name__contains="Targeting flag for survey")
        .values("team_id", "name", "id", "key")
    )


def query_saved_filters(period_start: datetime, period_end: datetime) -> QuerySet:
    return (
        SessionRecordingPlaylist.objects.exclude(
            (Q(name__isnull=True) | Q(name="Unnamed") | Q(name=""))
            & (
                Q(derived_name__isnull=True)
                | Q(derived_name="(Untitled)")
                | Q(derived_name="Unnamed")
                | Q(derived_name="")
            )
        )
        .exclude(deleted=True)
        .exclude(name__in=DEFAULT_PLAYLIST_NAMES)
        .exclude(type="collection")
        .exclude(type__isnull=True)
        .annotate(
            view_count=Count(
                "sessionrecordingplaylistviewed",
                filter=(
                    Q(sessionrecordingplaylistviewed__viewed_at__gt=period_start)
                    & Q(sessionrecordingplaylistviewed__viewed_at__lte=period_end)
                ),
            ),
        )
        .values("name", "short_id", "view_count")
        .order_by("-view_count")
    )


@database_sync_to_async
def queryset_to_list(qs: QuerySet):
    return list(qs)
