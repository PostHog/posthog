from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from django.db.models import Count, Q, QuerySet

from posthog.helpers.session_recording_playlist_templates import DEFAULT_PLAYLIST_NAMES
from posthog.models import Organization
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist

from products.dashboards.backend.models.dashboard import Dashboard
from products.error_tracking.backend.facade.api import query_new_error_issues as query_new_error_issues
from products.event_definitions.backend.models.event_definition import EventDefinition
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.growth.backend.models import ProductPushCampaign
from products.surveys.backend.models import Survey
from products.warehouse_sources.backend.facade.models import ExternalDataSource


def query_teams_for_digest(*, with_organization: bool = False) -> QuerySet:
    """Teams eligible for a digest, ordered by id.

    Pass `with_organization` only when the caller reads `Team.organization`.
    """
    # Excluding through the organization join makes Postgres read every organization row on
    # every call, to build a hash it then discards. A subquery hits the partial index on
    # for_internal_metrics, so the cost follows the team batch instead of the organization count.
    queryset = (
        Team.objects.exclude(is_demo=True)
        .exclude(organization_id__in=Organization.objects.filter(for_internal_metrics=True).values("id"))
        .order_by("id")
    )

    if with_organization:
        # all_users_with_access reads organization.available_product_features, a large JSON
        # column, so only the callers that ask for the organization pay to load it.
        return queryset.select_related("organization").only(
            "id",
            "project_id",
            "organization_id",
            "organization__id",
            "organization__available_product_features",
        )

    return queryset.only("id", "project_id", "organization_id")


def query_team_ids_for_digest() -> QuerySet:
    return query_teams_for_digest().values_list("id", flat=True)


def query_orgs_for_digest() -> QuerySet:
    return Organization.objects.exclude(Q(for_internal_metrics=True)).only("id", "name", "created_at").order_by("id")


def query_teams_for_organizations(organization_ids: Collection[UUID]) -> QuerySet:
    return (
        Team.objects.only("id", "name", "organization_id")
        .filter(organization_id__in=organization_ids)
        .exclude(is_demo=True)
        .order_by("id")
    )


def query_org_members(organization: Organization) -> QuerySet:
    return (
        OrganizationMembership.objects.filter(organization_id=organization.id)
        .select_related("user")
        .only("id", "user__distinct_id", "user__first_name", "user__email")
    ).order_by("id")


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
        .values("team_id", "name", "short_id", "view_count")
        .order_by("-view_count")
    )


def query_product_push_campaigns_for_organizations(
    organization_ids: Collection[UUID], period_end: datetime
) -> QuerySet:
    """Product push campaigns still running at the end of the digest period, newest first.

    Only ACTIVE campaigns qualify. A campaign that closed mid-period did so because the org
    either adopted the product or moved on from it, and neither is worth an email nudge.
    """
    return (
        ProductPushCampaign.objects.filter(
            organization_id__in=organization_ids,
            status=ProductPushCampaign.Status.ACTIVE,
            started_at__lte=period_end,
        )
        .order_by("-started_at")
        .values("organization_id", "product_key", "reason_text")
    )
