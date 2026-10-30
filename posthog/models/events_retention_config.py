from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import connection, models

from dateutil.relativedelta import relativedelta

from posthog.dataclasses import frozen
from posthog.models.organization import Organization
from posthog.models.team import Team

# Where neither the team nor its organization sets a window, once the team is admitted to plan-window deletion.
DEFAULT_RETENTION_WINDOW_MONTHS = 24

RETENTION_MONTHS_HELP = (
    "Events are deleted one calendar month at a time. A month is deleted only when every event in it is "
    "older than this many months. For example, with 13 months, the events of March 2025 are deleted on "
    "the first cleanup after 1 May 2026."
)


def _months_field(help_text: str) -> models.PositiveSmallIntegerField:
    return models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)], help_text=help_text
    )


def _delete_monthly_field(window: str) -> models.BooleanField:
    return models.BooleanField(
        default=False,
        help_text=f"Delete events older than {window} at every monthly cleanup. Otherwise they're deleted at the "
        "cleanup every 3 months, at least 3 months after the window gets shorter.",
    )


class OrganizationEventsRetentionConfig(models.Model):
    """Events deletion settings for an organization. Staff set the range, and organization admins set the default."""

    # db_constraint=False: a real FK constraint would take a SHARE ROW EXCLUSIVE
    # lock on posthog_organization (a hot table) while migrating.
    organization = models.OneToOneField(
        "posthog.Organization", on_delete=models.CASCADE, primary_key=True, db_constraint=False, related_name="+"
    )
    default_events_retention_months = _months_field(
        "Applies to every team in the organization that has no value of its own. Leave empty to use 24 months, or "
        f"the plan's window if that's shorter. {RETENTION_MONTHS_HELP}"
    )
    delete_monthly = _delete_monthly_field("the default")
    min_events_retention_months = _months_field("The shortest retention a team in this organization may set.")
    max_events_retention_months = _months_field("The longest retention a team in this organization may set.")

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="org_events_retention_months_positive",
                condition=(
                    (
                        models.Q(default_events_retention_months__isnull=True)
                        | models.Q(default_events_retention_months__gte=1)
                    )
                    & (
                        models.Q(min_events_retention_months__isnull=True)
                        | models.Q(min_events_retention_months__gte=1)
                    )
                    & (
                        models.Q(max_events_retention_months__isnull=True)
                        | models.Q(max_events_retention_months__gte=1)
                    )
                ),
            ),
            models.CheckConstraint(
                name="org_events_retention_months_ordered",
                condition=(
                    (
                        models.Q(min_events_retention_months__isnull=True)
                        | models.Q(default_events_retention_months__isnull=True)
                        | models.Q(min_events_retention_months__lte=models.F("default_events_retention_months"))
                    )
                    & (
                        models.Q(default_events_retention_months__isnull=True)
                        | models.Q(max_events_retention_months__isnull=True)
                        | models.Q(default_events_retention_months__lte=models.F("max_events_retention_months"))
                    )
                    & (
                        models.Q(min_events_retention_months__isnull=True)
                        | models.Q(max_events_retention_months__isnull=True)
                        | models.Q(min_events_retention_months__lte=models.F("max_events_retention_months"))
                    )
                ),
            ),
        ]

    def clean(self) -> None:
        lock_organization_retention(self.organization_id)
        low, default, high = (
            self.min_events_retention_months,
            self.default_events_retention_months,
            self.max_events_retention_months,
        )
        if low is not None and high is not None and low > high:
            raise ValidationError({"min_events_retention_months": "The minimum can't be more than the maximum."})
        if default is not None and not _within(default, low, high):
            raise ValidationError(
                {"default_events_retention_months": f"The default has to be {describe_months_range(low, high)}."}
            )

        out_of_range = sorted(
            team_id
            for team_id, months in TeamEventsRetentionConfig.objects.filter(
                team__organization_id=self.organization_id, events_retention_months__isnull=False
            ).values_list("team_id", "events_retention_months")
            if months is not None and not _within(months, low, high)
        )
        if out_of_range:
            raise ValidationError(
                f"Teams {', '.join(map(str, out_of_range))} have a retention that isn't {describe_months_range(low, high)}. "
                "Change those teams first, then save this range."
            )


class TeamEventsRetentionConfig(models.Model):
    """Events deletion setting for a team. Organization admins set it within the organization's range."""

    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True, db_constraint=False)
    events_retention_months = _months_field(
        "Overrides the organization's default and has to fall within the organization's range. Leave empty to use "
        f"the organization's default. {RETENTION_MONTHS_HELP}"
    )
    delete_monthly = _delete_monthly_field("this window")

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="team_events_retention_months_positive",
                condition=models.Q(events_retention_months__isnull=True) | models.Q(events_retention_months__gte=1),
            )
        ]

    def clean(self) -> None:
        if self.events_retention_months is None:
            return
        lock_organization_retention(self.team.organization_id)
        org_config = OrganizationEventsRetentionConfig.objects.filter(organization_id=self.team.organization_id).first()
        if org_config is None:
            return
        low, high = org_config.min_events_retention_months, org_config.max_events_retention_months
        if not _within(self.events_retention_months, low, high):
            raise ValidationError(
                {"events_retention_months": f"The organization allows {describe_months_range(low, high)}."}
            )


def lock_organization_retention(organization_id: object) -> None:
    # Django admin validates and saves a change form in one transaction, so this lock holds until the
    # save commits. A team value check and its organization's range check then cannot both read
    # stale values and pass. The lock key is the organization, not its hot posthog_organization row.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"events-retention:{organization_id}"])


def _within(months: int, low: int | None, high: int | None) -> bool:
    return (low is None or months >= low) and (high is None or months <= high)


def whole_month_cutoff(now: datetime, retention_months: int) -> datetime:
    """Start of the month that holds the instant ``retention_months`` before ``now``."""
    return (now - relativedelta(months=retention_months)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def describe_months_range(low: int | None, high: int | None) -> str:
    if low is not None and high is not None:
        return f"between {low} and {high} months"
    if low is not None:
        return f"at least {low} months"
    return f"at most {high} months"


@frozen
class TeamEventsRetention:
    organization_id: UUID
    team_id: int
    months: int
    delete_monthly: bool


def effective_events_retention(team_ids: Sequence[int] | None = None) -> list[TeamEventsRetention]:
    """Every team with a window set: its own, else its organization's default, with that row's monthly deletion."""
    team_table = Team._meta.db_table
    team_config_table = TeamEventsRetentionConfig._meta.db_table
    org_config_table = OrganizationEventsRetentionConfig._meta.db_table
    team_filter = "AND team.id = ANY(%s)" if team_ids is not None else ""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT team.organization_id,
                   team.id,
                   COALESCE(team_config.events_retention_months, org_config.default_events_retention_months),
                   CASE WHEN team_config.events_retention_months IS NOT NULL THEN team_config.delete_monthly
                        ELSE org_config.delete_monthly END
            FROM {team_table} AS team
            LEFT JOIN {team_config_table} AS team_config ON team_config.team_id = team.id
            LEFT JOIN {org_config_table} AS org_config ON org_config.organization_id = team.organization_id
            WHERE COALESCE(team_config.events_retention_months, org_config.default_events_retention_months) IS NOT NULL
            {team_filter}
            ORDER BY team.organization_id, team.id
            """,
            [list(team_ids)] if team_ids is not None else [],
        )
        return [
            TeamEventsRetention(
                organization_id=organization_id, team_id=team_id, months=months, delete_monthly=delete_monthly
            )
            for organization_id, team_id, months, delete_monthly in cursor.fetchall()
        ]


@frozen
class ConfiguredEventsRetention:
    organization_id: UUID
    organization_name: str
    team_id: int
    team_name: str
    team_months: int | None
    organization_default_months: int | None
    organization_min_months: int | None
    organization_max_months: int | None
    billing_months: int
    delete_monthly: bool

    @property
    def months(self) -> int | None:
        return self.team_months if self.team_months is not None else self.organization_default_months


# Every team that has a retention value of its own or belongs to an organization with a retention config.
_CONFIGURED_RETENTION_FROM = f"""
    FROM {Team._meta.db_table} AS team
    JOIN {Organization._meta.db_table} AS organization ON organization.id = team.organization_id
    LEFT JOIN {TeamEventsRetentionConfig._meta.db_table} AS team_config ON team_config.team_id = team.id
    LEFT JOIN {OrganizationEventsRetentionConfig._meta.db_table} AS org_config
        ON org_config.organization_id = team.organization_id
    WHERE org_config.organization_id IS NOT NULL OR team_config.events_retention_months IS NOT NULL
"""


def count_configured_events_retention() -> int:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) {_CONFIGURED_RETENTION_FROM}")
        [[count]] = cursor.fetchall()
        return count


def configured_events_retention(*, offset: int, limit: int) -> list[ConfiguredEventsRetention]:
    """One page of the teams that count_configured_events_retention counts, ordered by organization."""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT organization.id,
                   organization.name,
                   team.id,
                   team.name,
                   team_config.events_retention_months,
                   org_config.default_events_retention_months,
                   org_config.min_events_retention_months,
                   org_config.max_events_retention_months,
                   team.event_retention_months,
                   CASE WHEN team_config.events_retention_months IS NOT NULL THEN team_config.delete_monthly
                        ELSE COALESCE(org_config.delete_monthly, false) END
            {_CONFIGURED_RETENTION_FROM}
            ORDER BY organization.name, organization.id, team.id
            LIMIT %s OFFSET %s
            """,
            [limit, offset],
        )
        return [
            ConfiguredEventsRetention(
                organization_id=organization_id,
                organization_name=organization_name,
                team_id=team_id,
                team_name=team_name,
                team_months=team_months,
                organization_default_months=default_months,
                organization_min_months=min_months,
                organization_max_months=max_months,
                billing_months=billing_months,
                delete_monthly=delete_monthly,
            )
            for (
                organization_id,
                organization_name,
                team_id,
                team_name,
                team_months,
                default_months,
                min_months,
                max_months,
                billing_months,
                delete_monthly,
            ) in cursor.fetchall()
        ]
