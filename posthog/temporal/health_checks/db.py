from datetime import timedelta

from django.db.models import Exists, OuterRef, QuerySet
from django.utils import timezone

from posthog.models.health_issue import HealthIssue, _filter_existing_team_ids
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.temporal.health_checks.models import HealthCheckResult


def filter_recently_active_teams(teams: QuerySet[Team], active_since_days: int) -> QuerySet[Team]:
    """Teams with a member who logged in within `active_since_days`, the teams a scheduled check visits."""
    cutoff = timezone.now() - timedelta(days=active_since_days)
    return teams.filter(
        Exists(
            OrganizationMembership.objects.filter(
                organization_id=OuterRef("organization_id"), user__last_login__gte=cutoff
            )
        )
    )


def upsert_issues_with_deltas(
    kind: str,
    issues_by_team: dict[int, list[HealthCheckResult]],
) -> list[HealthIssue]:
    """Upsert health issues from a batch detection result.

    Returns the rows that became active in this call (newly created or
    transitioned from RESOLVED). These are the rows that should trigger
    a `firing` alert.
    """
    issues = [
        {
            "team_id": team_id,
            "severity": result.severity,
            "payload": result.payload,
            "unique_hash": HealthIssue.compute_unique_hash(kind, result.payload, result.hash_keys),
        }
        for team_id, results in issues_by_team.items()
        for result in results
    ]
    return HealthIssue.bulk_upsert(kind, issues)


def resolve_stale_issues_with_deltas(
    kind: str,
    issues_by_team: dict[int, list[HealthCheckResult]],
    healthy_team_ids: set[int],
) -> list[HealthIssue]:
    """Resolve issues for teams that no longer trip the check.

    Returns the rows that transitioned ACTIVE -> RESOLVED in this call.
    These are the rows that should trigger a `resolved` alert.
    """
    all_team_ids = healthy_team_ids | set(issues_by_team.keys())
    # Mirror the bulk_upsert filter — a team deleted mid-workflow already had
    # its issues cascaded away, so resolving on its ID is wasted work and
    # produces misleading `resolved` alerts if the IDs were ever reused.
    all_team_ids = _filter_existing_team_ids(all_team_ids)

    keep_hashes: dict[int, set[str]] = {}
    for team_id, results in issues_by_team.items():
        if team_id not in all_team_ids:
            continue
        keep_hashes[team_id] = {HealthIssue.compute_unique_hash(kind, r.payload, r.hash_keys) for r in results}

    return HealthIssue.bulk_resolve(kind, all_team_ids, keep_hashes or None)
