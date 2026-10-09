from uuid import UUID

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import connection, models

from posthog.dataclasses import frozen
from posthog.models.team import Team

RETENTION_MONTHS_HELP = (
    "Events are deleted one calendar month at a time. A month is deleted only when every event in it is "
    "older than this many months. For example, with 13 months, the events of March 2025 are deleted on "
    "the first monthly run after 1 May 2026."
)


def _months_field(help_text: str) -> models.PositiveSmallIntegerField:
    return models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)], help_text=help_text
    )


class OrganizationEventsRetentionConfig(models.Model):
    """Staff-only events deletion settings for an organization. No customer-facing serializer may write this model."""

    # db_constraint=False: a real FK constraint would take a SHARE ROW EXCLUSIVE
    # lock on posthog_organization (a hot table) while migrating.
    organization = models.OneToOneField(
        "posthog.Organization", on_delete=models.CASCADE, primary_key=True, db_constraint=False, related_name="+"
    )
    default_events_retention_months = _months_field(
        "Applies to every team in the organization that has no value of its own. Leave empty to keep the events "
        f"of those teams. {RETENTION_MONTHS_HELP}"
    )
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
        _lock_organization_retention(self.organization_id)
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
            if not _within(months, low, high)
        )
        if out_of_range:
            raise ValidationError(
                f"Teams {', '.join(map(str, out_of_range))} have a retention that isn't {describe_months_range(low, high)}. "
                "Change those teams first, then save this range."
            )


class TeamEventsRetentionConfig(models.Model):
    """Staff-only events deletion setting for a team. No customer-facing serializer may write this model."""

    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True, db_constraint=False)
    events_retention_months = _months_field(
        "Overrides the organization's default and has to fall within the organization's range. Leave empty to use "
        "the organization's default. Events are kept only when neither this nor the organization's default is set. "
        f"{RETENTION_MONTHS_HELP}"
    )

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
        _lock_organization_retention(self.team.organization_id)
        org_config = OrganizationEventsRetentionConfig.objects.filter(organization_id=self.team.organization_id).first()
        if org_config is None:
            return
        low, high = org_config.min_events_retention_months, org_config.max_events_retention_months
        if not _within(self.events_retention_months, low, high):
            raise ValidationError(
                {"events_retention_months": f"The organization allows {describe_months_range(low, high)}."}
            )


def _lock_organization_retention(organization_id: object) -> None:
    # Django admin validates and saves a change form in one transaction, so this lock holds until the
    # save commits. A team value check and its organization's range check then cannot both read
    # stale values and pass. The lock key is the organization, not its hot posthog_organization row.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"events-retention:{organization_id}"])


def _within(months: int, low: int | None, high: int | None) -> bool:
    return (low is None or months >= low) and (high is None or months <= high)


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


def effective_events_retention() -> list[TeamEventsRetention]:
    """Every team with an effective events retention: its own value, else its organization's default."""
    team_table = Team._meta.db_table
    team_config_table = TeamEventsRetentionConfig._meta.db_table
    org_config_table = OrganizationEventsRetentionConfig._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT team.organization_id,
                   team.id,
                   COALESCE(team_config.events_retention_months, org_config.default_events_retention_months)
            FROM {team_table} AS team
            LEFT JOIN {team_config_table} AS team_config ON team_config.team_id = team.id
            LEFT JOIN {org_config_table} AS org_config ON org_config.organization_id = team.organization_id
            WHERE COALESCE(team_config.events_retention_months, org_config.default_events_retention_months) IS NOT NULL
            ORDER BY team.organization_id, team.id
            """
        )
        return [
            TeamEventsRetention(organization_id=organization_id, team_id=team_id, months=months)
            for organization_id, team_id, months in cursor.fetchall()
        ]
