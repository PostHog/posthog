from datetime import datetime

from django.db.models import Q, QuerySet

from posthog.models.dashboard import Dashboard
from posthog.models.event_definition import EventDefinition
from posthog.models.experiment import Experiment
from posthog.models.feature_flag import FeatureFlag
from posthog.models.surveys.survey import Survey
from posthog.models.team import Team
from posthog.warehouse.models.external_data_source import ExternalDataSource


def query_teams_for_digest() -> QuerySet:
    return (
        Team.objects.select_related("organization")
        .exclude(Q(organization__for_internal_metrics=True) | Q(is_demo=True))
        .only("id", "name", "organization__id", "organization__name", "organization__created_at")
    )


def query_teams_with_new_dashboards(end: datetime, begin: datetime) -> QuerySet:
    return (
        Dashboard.objects.filter(created_at__gt=begin, created_at__lte=end)
        .exclude(name__contains="Generated Dashboard")
        .values("team_id", "name", "id")
    )


def query_teams_with_new_event_definitions(end: datetime, begin: datetime) -> QuerySet:
    return EventDefinition.objects.filter(created_at__gt=begin, created_at__lte=end).values("team_id", "name", "id")


def query_teams_with_experiments_launched(end: datetime, begin: datetime) -> QuerySet:
    return (
        Experiment.objects.filter(
            start_date__gt=begin,
            start_date__lte=end,
        )
        .exclude(
            end_date__gt=begin,
            end_date__lte=end,
        )
        .values("team_id", "name", "id", "start_date")
    )


def query_teams_with_experiments_completed(end: datetime, begin: datetime) -> QuerySet:
    return Experiment.objects.filter(end_date__gt=begin, end_date__lte=end).values(
        "team_id", "name", "id", "start_date", "end_date"
    )


def query_teams_with_new_external_data_sources(end: datetime, begin: datetime) -> QuerySet:
    return ExternalDataSource.objects.filter(created_at__gt=begin, created_at__lte=end, deleted=False).values(
        "team_id", "source_type", "id"
    )


def query_teams_with_surveys_launched(end: datetime, begin: datetime) -> QuerySet:
    return Survey.objects.filter(start_date__gt=begin, start_date__lte=end).values(
        "team_id", "name", "id", "description", "start_date"
    )


def query_teams_with_new_feature_flags(end: datetime, begin: datetime) -> QuerySet:
    return (
        FeatureFlag.objects.filter(
            created_at__gt=begin,
            created_at__lte=end,
            deleted=False,
        )
        .exclude(name__contains="Feature Flag for Experiment")
        .exclude(name__contains="Targeting flag for survey")
        .values("team_id", "name", "id", "key")
    )
