import datetime
import collections
from typing import Any, Optional, cast

from django.conf import settings
from django.db.models import Count, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

import structlog
from celery import shared_task

from posthog.email import EMAIL_TASK_KWARGS, EmailMessage, is_email_available
from posthog.models import OrganizationMembership, Team
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.email import NotificationSetting, NotificationSettingType, get_members_to_notify

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.data_modeling.backend.facade.api import (
    declared_targets_by_saved_query,
    get_node_ids_for_saved_queries,
    suspended_saved_query_ids_by_team,
    suspension_state_for_saved_query,
)
from products.data_modeling.backend.facade.enums import DataModelingJobEngine
from products.data_modeling.backend.models.data_modeling_job import DataModelingJob
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

logger = structlog.get_logger(__name__)


def get_members_to_notify_of_matview_failure(
    team: Team, delivery: NotificationSettingType
) -> list[OrganizationMembership]:
    """Members who turned on materialization failure emails and this way of delivering them.

    Two settings gate these emails, so both are checked: the one that turns them on at all, and
    the one for the digest or the immediate email.
    """
    opted_into_delivery = {membership.id for membership in get_members_to_notify(team, delivery)}
    return [
        membership
        for membership in get_members_to_notify(team, NotificationSetting.MATERIALIZED_VIEW_SYNC_FAILED.value)
        if membership.id in opted_into_delivery
    ]


def filter_members_by_warehouse_access(
    memberships: list[OrganizationMembership],
    team: Team,
    saved_query: Optional[DataWarehouseSavedQuery] = None,
) -> list[OrganizationMembership]:
    """Drop members who cannot view the warehouse objects an email would name.

    Two gates, because a deny can sit at either level. The resource gate covers members with
    no warehouse access at all. The object gate covers a deny on one view, which the resource
    gate cannot see, and repeats what `Database._is_warehouse_view_denied` does when the same
    member opens that view. Pass `saved_query` whenever the email names a single view.

    Falls back to the unfiltered list when access controls are unavailable: not being able to
    check must not silently stop every failure email.
    """
    if not memberships:
        return memberships

    def allowed(membership: OrganizationMembership) -> bool:
        access = UserAccessControl(membership.user, team)
        if not access.check_access_level_for_resource("warehouse_objects", "viewer"):
            return False
        if saved_query is None or access.is_organization_admin:
            return True
        return bool(access.check_access_level_for_object(saved_query, required_level="viewer"))

    try:
        if not UserAccessControl(memberships[0].user, team).access_controls_supported:
            return memberships
        return [membership for membership in memberships if allowed(membership)]
    except Exception:
        logger.exception("Warehouse access check failed, sending to all subscribed members", team_id=team.id)
        return memberships


def group_members_by_visible_views(
    memberships: list[OrganizationMembership],
    team: Team,
    views: list[dict],
    queries: dict[str, DataWarehouseSavedQuery],
) -> list[tuple[list[OrganizationMembership], list[dict]]]:
    """Split a digest into one audience per set of views its members may open.

    `filter_members_by_warehouse_access` takes one view, so a digest naming many of them can only
    use its resource gate. A deny on a single view would then still reach every subscriber as a
    name, an error and a link. Grouping repeats the object check `Database._is_warehouse_view_denied`
    makes when the same member opens that view.

    Each member lands in exactly one group, so every audience can share one campaign key.

    Falls back to one audience holding every view when access controls are unavailable: not being
    able to check must not silently stop the whole digest.

    Raises when every member's check failed, so the task retries rather than reporting a send it
    never made. A member dropped while others are grouped is a real deny often enough to swallow.
    """
    if not memberships:
        return []

    try:
        if not UserAccessControl(memberships[0].user, team).access_controls_supported:
            return [(memberships, views)]
    except Exception:
        logger.exception("Warehouse access check failed, sending one digest to all members", team_id=team.id)
        return [(memberships, views)]

    audiences: dict[tuple[str, ...], list[OrganizationMembership]] = {}
    last_failure: Exception | None = None
    for membership in memberships:
        try:
            access = UserAccessControl(membership.user, team)
            if access.is_organization_admin:
                visible = tuple(str(view["id"]) for view in views)
            else:
                visible = tuple(
                    str(view["id"])
                    for view in views
                    if access.check_access_level_for_object(queries[str(view["id"])], required_level="viewer")
                )
        except Exception as error:
            # Dropping only the member whose check failed. Admitting them instead would name a view,
            # its error and its link to someone the same check may be about to deny.
            logger.exception("Warehouse access check failed for one member", team_id=team.id)
            last_failure = error
            continue
        if visible:
            audiences.setdefault(visible, []).append(membership)

    if last_failure is not None and not audiences:
        raise last_failure

    by_id = {str(view["id"]): view for view in views}
    return [(members, [by_id[view_id] for view_id in visible]) for visible, members in audiences.items()]


MAX_VIEWS_PER_DIGEST_EMAIL = 30
MAX_ERROR_CHARS = 255
# Most urgent first: this order drives the email layout, the subject line and which rows the cap keeps.
DIGEST_SECTIONS: dict[str, dict[str, Any]] = {
    "action": {
        "title": "Needs action",
        "description": "These views stopped running. They won't update until you fix them.",
        "color": "#dc3545",
        "verbs": ("needs action", "need action"),
    },
    "new": {
        "title": "Started failing",
        "description": "These started failing in the last 24 hours. They retry on their next scheduled run, so a temporary problem can clear on its own.",
        "color": "#fd7e14",
        "verbs": ("started failing", "started failing"),
    },
    "ongoing": {
        "title": "Still failing",
        "description": "These have failed every run for more than a day. Retrying hasn't fixed them, so they likely need a change.",
        "color": "#9ca3af",
        "verbs": ("is still failing", "are still failing"),
    },
}
DIGEST_SECTION_ORDER = tuple(DIGEST_SECTIONS)
# Older than any job, so a view that never succeeded counts every failure in its streak.
STREAK_FLOOR_BEFORE_ANY_RUN = datetime.datetime(1970, 1, 1, tzinfo=datetime.UTC)


def _matview_digest_summary(counts: dict[str, int]) -> str:
    """Count each section, e.g. "1 materialized view needs action, 3 started failing"."""
    parts: list[str] = []
    for key in DIGEST_SECTION_ORDER:
        count = counts.get(key, 0)
        if not count:
            continue
        verb = DIGEST_SECTIONS[key]["verbs"][count != 1]
        if not parts:
            noun = "materialized view" if count == 1 else "materialized views"
            parts.append(f"{count} {noun} {verb}")
        else:
            parts.append(f"{count} {verb}")
    return ", ".join(parts) or "Materialized view failures"


@shared_task(ignore_result=True, name="posthog.tasks.email.send_matview_failure_digest")
@skip_team_scope_audit
def send_matview_failure_digest() -> None:

    if not is_email_available(with_absolute_urls=True):
        logger.warning("Email service is not available for materialized view digest")
        return

    cutoff = timezone.now() - datetime.timedelta(hours=24)

    # Latest DataModelingJob is the failure source of truth because v2 does not update SavedQuery.status.
    # Managed warehouse shadow jobs share saved_query_id and finalize after ClickHouse, so they must not stand in for the serving job.
    latest_job = DataModelingJob.objects.filter(
        saved_query_id=OuterRef("id"), engine=DataModelingJobEngine.CLICKHOUSE
    ).order_by("-last_run_at")

    failed_queries = (
        DataWarehouseSavedQuery.objects.exclude(deleted=True)
        .annotate(
            latest_job_status=Subquery(latest_job.values("status")[:1]),
            latest_job_run_at=Subquery(latest_job.values("last_run_at")[:1]),
        )
        .filter(
            latest_job_status=DataModelingJob.Status.FAILED,
            latest_job_run_at__gte=cutoff,
        )
        # Identifiers only: a full row also detoasts six JSON columns and the error text,
        # for every saved query in every team.
        .values("id", "team_id")
    )

    failed_ids_by_team: dict[int, list[str]] = {}
    for sq in failed_queries:
        failed_ids_by_team.setdefault(sq["team_id"], []).append(str(sq["id"]))

    # A suspended view runs no jobs, so its last failure ages out of the 24h window above.
    suspended_ids_by_team = suspended_saved_query_ids_by_team(DataModelingJobEngine.CLICKHOUSE)

    team_ids = sorted(set(failed_ids_by_team) | set(suspended_ids_by_team))
    if not team_ids:
        logger.info("No matview failures found")
        return

    logger.info("Found %d teams with matview failures", len(team_ids))

    for team_id in team_ids:
        suspended_ids = suspended_ids_by_team.get(team_id, [])
        suspended = set(suspended_ids)
        # A suspended view failed too, so report it once, under the status that asks for action.
        failed_ids = [qid for qid in failed_ids_by_team.get(team_id, []) if qid not in suspended]
        if not failed_ids and not suspended_ids:
            continue
        send_team_matview_failure_digest.delay(team_id, failed_ids, suspended_ids)
        logger.info(
            "Dispatching matview failure digest for team %d with %d failed and %d suspended views.",
            team_id,
            len(failed_ids),
            len(suspended_ids),
        )

    logger.info("Completed materialized view failure digest fan-out")


@shared_task(**EMAIL_TASK_KWARGS, name="posthog.tasks.email.send_team_matview_failure_digest")
@skip_team_scope_audit
def send_team_matview_failure_digest(team_id: int, failed_query_ids: list[str], suspended_query_ids: list[str]) -> None:

    if not is_email_available(with_absolute_urls=True):
        return

    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.warning("Team %d not found for matview failure digest", team_id)
        return

    memberships_to_email = filter_members_by_warehouse_access(
        get_members_to_notify_of_matview_failure(team, NotificationSetting.MATERIALIZED_VIEW_SYNC_FAILED_DAILY.value),
        team,
    )
    if not memberships_to_email:
        return

    all_ids = list(set(failed_query_ids + suspended_query_ids))
    clickhouse_jobs = DataModelingJob.objects.filter(
        saved_query_id=OuterRef("id"), engine=DataModelingJobEngine.CLICKHOUSE, last_run_at__isnull=False
    )
    last_success_at = (
        clickhouse_jobs.filter(status=DataModelingJob.Status.COMPLETED).order_by("-last_run_at").values("last_run_at")
    )
    streak_jobs = clickhouse_jobs.filter(status=DataModelingJob.Status.FAILED, last_run_at__gt=OuterRef("streak_floor"))
    queries: dict[str, DataWarehouseSavedQuery] = {
        str(sq.id): sq
        for sq in DataWarehouseSavedQuery.objects.filter(id__in=all_ids, team_id=team_id).annotate(
            streak_floor=Coalesce(Subquery(last_success_at[:1]), Value(STREAK_FLOOR_BEFORE_ANY_RUN)),
            failing_since=Subquery(streak_jobs.order_by("last_run_at").values("last_run_at")[:1]),
            failed_runs=Subquery(
                streak_jobs.order_by().values("saved_query_id").annotate(n=Count("id")).values("n")[:1]
            ),
        )
    }
    new_failure_cutoff = timezone.now() - datetime.timedelta(hours=24)
    declared_targets = declared_targets_by_saved_query(team_id, all_ids)
    node_ids = get_node_ids_for_saved_queries(team_id, all_ids)

    latest_jobs: dict[str, DataModelingJob] = {}
    for latest_job in (
        DataModelingJob.objects.filter(saved_query_id__in=all_ids, engine=DataModelingJobEngine.CLICKHOUSE)
        .order_by("saved_query_id", "-last_run_at")
        .distinct("saved_query_id")
    ):
        latest_jobs[str(latest_job.saved_query_id)] = latest_job

    views = []
    for qid, suspended in [(qid, False) for qid in failed_query_ids] + [(qid, True) for qid in suspended_query_ids]:
        sq = queries.get(qid)
        if not sq:
            continue
        job: DataModelingJob | None = latest_jobs.get(qid)
        # Suspending rewrites the job error to lead with a sentence about the suspension, which the
        # status column already says. The marker kept the error that caused it, so read that instead
        # and leave the row's 90 characters to the part the reader can act on.
        marker_reason: str | None = (
            suspension_state_for_saved_query(sq).get(str(DataModelingJobEngine.CLICKHOUSE), {}).get("reason")
            if suspended
            else None
        )
        error = marker_reason or (job.error if job else None) or sq.latest_error or "Unknown error"
        if len(error) > MAX_ERROR_CHARS:
            error = error[: MAX_ERROR_CHARS - 3] + "..."
        run_at = (job.last_run_at if job else None) or sq.last_run_at
        # `is_materialized` stays True after a pause, so read the cadence and the table instead.
        # Pausing clears the cadence and keeps the table; reverting clears both.
        if qid in declared_targets:
            schedule = "scheduled"
        elif sq.table_id is not None:
            schedule = "paused"
        else:
            schedule = "reverted"
        failing_since: datetime.datetime | None = getattr(sq, "failing_since", None) or run_at
        if suspended or schedule != "scheduled":
            section = "action"
        elif failing_since is None or failing_since >= new_failure_cutoff:
            section = "new"
        else:
            section = "ongoing"
        views.append(
            {
                "id": str(sq.id),
                "name": sq.name,
                "error": error,
                "last_run_at": run_at.strftime("%b %d, %H:%M UTC") if run_at else "Unknown",
                "last_run_at_ts": run_at.timestamp() if run_at else 0,
                "failing_since": failing_since.strftime("%b %d, %H:%M UTC") if failing_since else "Unknown",
                "failed_runs": getattr(sq, "failed_runs", None) or 1,
                "section": section,
                "suspended": suspended,
                "schedule": schedule,
                "url": settings.SITE_URL + matview_view_path(team_id, qid, node_ids.get(qid)),
            }
        )

    if not views:
        logger.warning("No failed or suspended views found")
        return

    # Rows needing action outrank new failures, which outrank old ones, so the cap keeps them.
    views.sort(
        key=lambda v: (
            DIGEST_SECTION_ORDER.index(v["section"]),
            not v["suspended"],
            -cast(float, v["last_run_at_ts"]),
        )
    )
    for v in views:
        v.pop("last_run_at_ts", None)

    today = datetime.date.today().strftime("%Y-%m-%d")
    campaign_key = f"matview_failure_digest_{team_id}_{today}"

    for memberships, visible_views in group_members_by_visible_views(memberships_to_email, team, views, queries):
        omitted_count = max(0, len(visible_views) - MAX_VIEWS_PER_DIGEST_EMAIL)
        listed_views = visible_views[:MAX_VIEWS_PER_DIGEST_EMAIL]

        # Count before the cap, so the subject reflects every failing view the reader can see.
        summary = _matview_digest_summary(collections.Counter(v["section"] for v in visible_views))
        sections = [
            {
                "key": key,
                "title": DIGEST_SECTIONS[key]["title"],
                "description": DIGEST_SECTIONS[key]["description"],
                "color": DIGEST_SECTIONS[key]["color"],
                "views": [v for v in listed_views if v["section"] == key],
            }
            for key in DIGEST_SECTION_ORDER
        ]
        message = EmailMessage(
            campaign_key=campaign_key,
            subject=f"PostHog: {summary} in {team.name}",
            template_name="matview_failure_digest",
            template_context={
                "team": team,
                "views": listed_views,
                "sections": [section for section in sections if section["views"]],
                "summary": summary,
                "omitted_count": omitted_count,
                "views_url": f"{settings.SITE_URL}/project/{team_id}/models",
            },
        )

        for membership in memberships:
            message.add_user_recipient(membership.user)
        message.send()

        logger.info(
            "Sent materialized view failure digest email for team %d: %d views (%d suspended) to %d members",
            team_id,
            len(listed_views),
            sum(1 for v in listed_views if v["suspended"]),
            len(memberships),
        )


def matview_view_path(team_id: int, saved_query_id: str, node_id: str | None) -> str:
    """Where a failure email or notification sends the reader: the view's node detail, which shows its runs and error.

    A view with no DAG node has no node detail page, so it falls back to the SQL editor.
    """
    if node_id:
        return f"/project/{team_id}/models/{node_id}"
    return f"/project/{team_id}/sql?open_view={saved_query_id}"


@shared_task(**EMAIL_TASK_KWARGS, name="posthog.tasks.email.send_matview_failure_immediate_email")
@skip_team_scope_audit
def send_matview_failure_immediate_email(
    team_id: int, saved_query_id: str, job_id: str, suspended: bool = False
) -> None:
    """Email members who asked for a materialization failure email as it happens.

    Dispatched on the first failure of a streak, and again when the streak suspends the view;
    the job-scoped campaign key makes redelivery idempotent per recipient.
    """

    if not is_email_available(with_absolute_urls=True):
        return

    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.warning("Team %d not found for matview failure email", team_id)
        return

    saved_query = (
        DataWarehouseSavedQuery.objects.filter(id=saved_query_id, team_id=team_id).exclude(deleted=True).first()
    )
    if saved_query is None:
        return

    memberships_to_email = filter_members_by_warehouse_access(
        get_members_to_notify_of_matview_failure(
            team, NotificationSetting.MATERIALIZED_VIEW_SYNC_FAILED_IMMEDIATE.value
        ),
        team,
        saved_query,
    )
    if not memberships_to_email:
        return

    job = DataModelingJob.objects.filter(id=job_id, team_id=team_id).first()
    error = (job.error if job else None) or saved_query.latest_error or ""
    node_id = get_node_ids_for_saved_queries(team_id, [saved_query.id]).get(str(saved_query.id))
    if len(error) > MAX_ERROR_CHARS:
        error = error[: MAX_ERROR_CHARS - 3] + "..."

    if suspended:
        campaign_key = f"matview_suspended_{saved_query_id}_{job_id}"
        subject = f"PostHog: Materialized view '{saved_query.name}' was suspended in {team.name}"
    else:
        campaign_key = f"matview_failure_immediate_{saved_query_id}_{job_id}"
        subject = f"PostHog: Materialized view '{saved_query.name}' failed in {team.name}"
    message = EmailMessage(
        campaign_key=campaign_key,
        subject=subject,
        template_name="saved_query_materialization_failure",
        template_context={
            "team": team,
            "saved_query_name": saved_query.name,
            "saved_query_id": str(saved_query.id),
            "view_url": settings.SITE_URL + matview_view_path(team_id, str(saved_query.id), node_id),
            "error": error,
            "suspended": suspended,
        },
    )
    for membership in memberships_to_email:
        message.add_user_recipient(membership.user)
    message.send()

    logger.info(
        "Sent immediate materialized view failure email for team %d, saved query %s",
        team_id,
        saved_query_id,
    )
