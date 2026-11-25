import time
from collections.abc import Collection, Mapping
from datetime import datetime, timedelta
from itertools import batched

from django.conf import settings
from django.db import OperationalError, close_old_connections
from django.db.models import Exists, OuterRef, QuerySet
from django.utils import timezone

import structlog
import posthoganalytics
from prometheus_client import Gauge
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.email import EmailMessage, is_email_available
from posthog.exceptions_capture import capture_exception
from posthog.metrics import pushed_metrics_registry
from posthog.models import Team
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_notification_lock import GovernedSetting, notification_locks_for_users
from posthog.models.user import User
from posthog.sync import database_sync_to_async
from posthog.tasks.email import NotificationSetting, should_send_notification
from posthog.temporal.common.digest import OrgBatchPageResult, paginate_index, paginate_keyset
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.user_permissions import UserPermissions

from products.access_control.backend.facade.user_access_control import UserAccessControl

from ...facade.contracts import DigestRow, DigestSource
from ...logic.digest_sources import load_digest_sources
from ...logic.pending_review import TeamPendingReview, build_org_pending_reviews, groups_visible_to
from .email_context import build_subject, build_template_context, pending_rows
from .types import (
    DATA_CATALOG_DIGEST_EMAIL_UNAVAILABLE_TYPE,
    NEW_ITEMS_WINDOW,
    DataCatalogWeeklyDigestInput,
    DigestBatchInput,
    DigestBatchResult,
    DigestOutcome,
    OrgBatchPageInput,
    OrgDigestCounts,
    ProjectDigest,
    SendTestDigestInput,
)

logger = structlog.get_logger(__name__)

DIGEST_FLAG_KEY = "data-catalog-weekly-digest"
EMAIL_TEMPLATE_NAME = "data_catalog_weekly_digest"


def _get_org_queryset_for_digest(input: DataCatalogWeeklyDigestInput) -> tuple[QuerySet[Organization], datetime | None]:
    qs = Organization.objects.all()
    cutoff = None
    if input.active_since_days is not None and input.active_since_days > 0:
        cutoff = timezone.now() - timedelta(days=input.active_since_days)
        qs = qs.filter(
            Exists(
                OrganizationMembership.objects.filter(
                    organization_id=OuterRef("id"),
                    user__last_login__gte=cutoff,
                )
            )
        )
    return qs, cutoff


def _get_org_batch_page(input: OrgBatchPageInput) -> OrgBatchPageResult:
    """Raises non-retryable `ApplicationError` when email is globally unavailable
    — per-org skips would silently absorb the outage.
    """
    close_old_connections()

    if not is_email_available(with_absolute_urls=True):
        raise ApplicationError(
            "Data catalog weekly digest: email service is unavailable",
            type=DATA_CATALOG_DIGEST_EMAIL_UNAVAILABLE_TYPE,
            non_retryable=True,
        )

    workflow_input = input.workflow_input
    cutoff: datetime | None = None

    if workflow_input.org_ids is not None:
        page_org_ids, next_cursor = paginate_index(list(workflow_input.org_ids), input.cursor, input.page_size)
        source = "configured"
    else:
        qs, cutoff = _get_org_queryset_for_digest(workflow_input)
        page_org_ids, next_cursor = paginate_keyset(qs, input.cursor, input.page_size)
        source = "keyset"

    batches = [list(b) for b in batched(page_org_ids, workflow_input.batch_size, strict=False)]
    logger.info(
        "data catalog digest org batch page",
        source=source,
        count=len(page_org_ids),
        batch_count=len(batches),
        batch_size=workflow_input.batch_size,
        cursor=input.cursor,
        next_cursor=next_cursor,
        active_since_days=workflow_input.active_since_days,
        cutoff=cutoff.isoformat() if cutoff else None,
    )
    return OrgBatchPageResult(batches=batches, cursor=next_cursor)


@activity.defn(name="data-catalog-digest-get-org-batch-page")
async def get_org_batch_page(input: OrgBatchPageInput) -> OrgBatchPageResult:
    return await database_sync_to_async(_get_org_batch_page, thread_sensitive=False)(input)


def _is_user_flag_enabled(user: User, org_id: str) -> bool:
    try:
        return bool(
            posthoganalytics.feature_enabled(
                DIGEST_FLAG_KEY,
                distinct_id=str(user.distinct_id),
                groups={"organization": org_id},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as e:
        logger.warning(
            "data catalog digest: flag eval failed, treating user as not enabled",
            user_id=str(user.uuid),
            org_id=org_id,
            error=str(e),
        )
        capture_exception(e, {"user_id": str(user.uuid), "org_id": org_id})
        return False


def _send_digest_for_user(
    *,
    user: User,
    org: Organization,
    membership: OrganizationMembership,
    reviews: dict[int, TeamPendingReview],
    teams_by_id: dict[int, Team],
    date_suffix: str,
    new_since: datetime | None = None,
    source_teams: Mapping[DigestSource, Collection[int]] | None = None,
    locks: dict[GovernedSetting, bool] | None = None,
    dry_run: bool = False,
    test: bool = False,
) -> DigestOutcome:
    """`test=True` bypasses the notification opt-in and forces a unique campaign key so dedupe
    never blocks delivery. Project access is always enforced, catalog rows need catalog access, and each
    source enforces the access its own rows need.
    """
    if not test and not should_send_notification(
        user, NotificationSetting.DATA_CATALOG_WEEKLY_DIGEST.value, locks=locks
    ):
        return DigestOutcome.SKIPPED_OPTOUT

    user_perms = UserPermissions(user)

    def has_project_access(team: Team) -> bool:
        return user_perms.team(team).effective_membership_level_for_parent_membership(org, membership) is not None

    source_teams = source_teams or {}
    new_since = new_since or _new_since()
    candidate_team_ids = set(reviews).union(*source_teams.values())
    projects = [
        project
        for team_id in sorted(candidate_team_ids)
        if has_project_access(teams_by_id[team_id])
        and (project := _project_digest(teams_by_id[team_id], user, reviews.get(team_id), source_teams, new_since))
    ]
    if not projects:
        return DigestOutcome.SKIPPED_NO_DATA

    if not test and not any(project.new_total for project in projects):
        return DigestOutcome.SKIPPED_NOTHING_NEW

    if dry_run:
        return DigestOutcome.DRY_RUN

    template_context = build_template_context(org, projects)

    campaign_key = f"data_catalog_weekly_digest_{org.id}_{user.uuid}_{date_suffix}"
    if test:
        campaign_key = f"{campaign_key}_test_{int(timezone.now().timestamp())}"

    try:
        message = EmailMessage(
            campaign_key=campaign_key,
            subject=build_subject(template_context["new_total"], template_context["total"]),
            template_name=EMAIL_TEMPLATE_NAME,
            template_context=template_context,
        )
        message.add_user_recipient(user)
        message.send()
    except Exception as e:
        if test:
            raise
        logger.warning(
            "failed to send data catalog digest email",
            org_id=str(org.id),
            user_id=str(user.uuid),
            error=str(e),
        )
        capture_exception(e, {"org_id": str(org.id), "user_id": str(user.uuid)})
        return DigestOutcome.FAILED

    return DigestOutcome.SENT


def _project_digest(
    team: Team,
    user: User,
    review: TeamPendingReview | None,
    source_teams: Mapping[DigestSource, Collection[int]],
    new_since: datetime,
) -> ProjectDigest | None:
    rows = _catalog_rows(team, user, review, new_since) if review else []
    for source, team_ids in source_teams.items():
        if team.id in team_ids:
            rows += _source_rows(source, team, user, new_since)
    if not rows:
        return None
    return ProjectDigest(team_id=team.id, team_name=team.name, rows=rows)


def _catalog_rows(team: Team, user: User, review: TeamPendingReview, new_since: datetime) -> list[DigestRow]:
    """The catalog queues as `user` sees them. A failure drops this project's catalog rows, so other readers still get mail."""
    try:
        # nosemgrep: authorization-through-sdk -- data_catalog cannot import the SDK (package cycle), and metrics_visible_to_user needs this object
        if not (access := UserAccessControl(user=user, team=team)).check_access_level_for_resource(
            "data_catalog", "viewer"
        ):
            return []
        return pending_rows(groups_visible_to(review, team, user, access, new_since))
    except Exception as e:
        logger.warning("data catalog digest catalog rows failed", team_id=team.id, user_id=str(user.uuid), error=str(e))
        capture_exception(e, {"team_id": team.id, "user_id": str(user.uuid)})
        return []


def _source_rows(source: DigestSource, team: Team, user: User, new_since: datetime) -> list[DigestRow]:
    try:
        return source.rows(team, user, new_since)
    except Exception as e:
        logger.warning("data catalog digest source failed", source=source.name, team_id=team.id, error=str(e))
        capture_exception(e, {"source": source.name, "team_id": team.id})
        return []


def _source_teams(teams: list[Team]) -> dict[DigestSource, frozenset[int]]:
    """For each source, the teams it has rows for. A source that fails to load or raises adds no team."""
    source_teams: dict[DigestSource, frozenset[int]] = {}
    for source in _loaded_sources():
        try:
            source_teams[source] = frozenset(source.teams_with_rows(teams))
        except Exception as e:
            logger.warning("data catalog digest source failed", source=source.name, error=str(e))
            capture_exception(e, {"source": source.name})
    return source_teams


def _loaded_sources() -> tuple[DigestSource, ...]:
    try:
        return load_digest_sources()
    except Exception as e:
        logger.warning("data catalog digest sources failed to load", error=str(e))
        capture_exception(e)
        return ()


def _new_since() -> datetime:
    return timezone.now() - NEW_ITEMS_WINDOW


def _project_teams(org_id: str) -> dict[int, Team]:
    """Project-level teams only. A child environment resolves to its parent's catalog, so
    including one would count the same proposals a second time.
    """
    teams = Team.objects.filter(organization_id=org_id, parent_team_id__isnull=True)
    return {team.id: team for team in teams}


def _build_and_send_for_org(org_id: str, dry_run: bool = False, new_since: datetime | None = None) -> OrgDigestCounts:
    close_old_connections()

    counts = OrgDigestCounts()

    try:
        org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        logger.warning("Organization not found for data catalog weekly digest", org_id=org_id)
        counts.skipped_reason = "org_not_found"
        return counts

    # The app and the API refuse a deactivated or pending-deletion organization, so mail must too:
    # every link in the digest would land on the block page. Only an explicit False deactivates,
    # because `is_active` is nullable and a null means the organization was never deactivated.
    if org.is_pending_deletion or org.is_active is False:
        counts.skipped_reason = "org_blocked"
        return counts

    teams_by_id = _project_teams(org_id)
    if not teams_by_id:
        counts.skipped_reason = "no_teams"
        return counts

    build_start = time.monotonic()
    new_since = new_since or _new_since()
    build = build_org_pending_reviews(list(teams_by_id.values()), new_since=new_since)
    source_teams = _source_teams(list(teams_by_id.values()))
    counts.build_duration = time.monotonic() - build_start
    counts.team_count = len(build.reviews)
    counts.teams_failed = len(build.failed_team_ids)
    reviews = build.reviews

    if not reviews and not any(source_teams.values()):
        counts.skipped_reason = "nothing_pending"
        return counts

    memberships = list(
        OrganizationMembership.objects.select_related("user").filter(organization_id=org.id, user__is_active=True)
    )
    targeted_memberships = [m for m in memberships if _is_user_flag_enabled(m.user, str(org.id))]
    if not targeted_memberships:
        counts.skipped_reason = "no_targeted_memberships"
        return counts

    locks_by_user = notification_locks_for_users(
        [membership.user_id for membership in targeted_memberships], organization_id=org.id
    )
    date_suffix = timezone.now().strftime("%Y-%W")

    send_start = time.monotonic()
    for membership in targeted_memberships:
        outcome = _send_digest_for_user(
            user=membership.user,
            org=org,
            membership=membership,
            reviews=reviews,
            teams_by_id=teams_by_id,
            date_suffix=date_suffix,
            new_since=new_since,
            source_teams=source_teams,
            locks=locks_by_user.get(membership.user_id, {}),
            dry_run=dry_run,
        )
        if outcome in (DigestOutcome.SENT, DigestOutcome.DRY_RUN):
            counts.sent += 1
        elif outcome == DigestOutcome.SKIPPED_OPTOUT:
            counts.skipped_optout += 1
        elif outcome == DigestOutcome.SKIPPED_NO_DATA:
            counts.skipped_no_data += 1
        elif outcome == DigestOutcome.SKIPPED_NOTHING_NEW:
            counts.skipped_nothing_new += 1
        elif outcome == DigestOutcome.FAILED:
            counts.failed += 1
    counts.send_duration = time.monotonic() - send_start

    logger.info(
        "Sent data catalog weekly digest for org",
        org_id=org_id,
        sent_count=counts.sent,
        skipped_optout=counts.skipped_optout,
        skipped_no_data=counts.skipped_no_data,
        skipped_nothing_new=counts.skipped_nothing_new,
        failed=counts.failed,
        team_count=counts.team_count,
        teams_failed=counts.teams_failed,
    )
    return counts


def _build_and_send_for_org_with_retry(
    org_id: str, dry_run: bool = False, new_since: datetime | None = None
) -> OrgDigestCounts:
    """Retries once when the database drops the connection. The retry starts with
    `close_old_connections`, which replaces the broken connection. The campaign key dedupes
    any email that the first attempt already sent.
    """
    try:
        return _build_and_send_for_org(org_id, dry_run=dry_run, new_since=new_since)
    except OperationalError as e:
        logger.warning("Data catalog digest hit a database error for org, retrying once", org_id=org_id, error=str(e))
        return _build_and_send_for_org(org_id, dry_run=dry_run, new_since=new_since)


def _run_digest_batch(input: DigestBatchInput) -> DigestBatchResult:
    close_old_connections()
    new_since = datetime.fromisoformat(input.new_since) if input.new_since else _new_since()

    totals = DigestBatchResult(batch_size=len(input.org_ids))

    for org_id in input.org_ids:
        try:
            org_counts = _build_and_send_for_org_with_retry(org_id, dry_run=input.dry_run, new_since=new_since)
        except Exception as e:
            logger.exception("Data catalog digest failed for org", org_id=org_id, error=str(e))
            capture_exception(e, {"org_id": org_id})
            totals.orgs_failed += 1
            continue

        if org_counts.skipped_reason is not None:
            totals.orgs_skipped += 1
            continue

        totals.orgs_processed += 1
        totals.emails_sent += org_counts.sent
        totals.emails_skipped_optout += org_counts.skipped_optout
        totals.emails_skipped_no_data += org_counts.skipped_no_data
        totals.emails_skipped_nothing_new += org_counts.skipped_nothing_new
        totals.emails_failed += org_counts.failed
        totals.teams_failed += org_counts.teams_failed
        totals.build_duration += org_counts.build_duration
        totals.send_duration += org_counts.send_duration

    return totals


@activity.defn(name="data-catalog-digest-run-batch")
async def run_digest_batch(input: DigestBatchInput) -> DigestBatchResult:
    """Per-org failures are isolated (logged and counted) so one bad org never poisons the batch."""
    async with Heartbeater():
        return await database_sync_to_async(_run_digest_batch, thread_sensitive=False)(input)


def _push_digest_metrics(totals: DigestBatchResult, success: bool) -> None:
    if not settings.PROM_PUSHGATEWAY_ADDRESS:
        return

    try:
        with pushed_metrics_registry("data_catalog_weekly_digest") as registry:
            duration_gauge = Gauge(
                "posthog_data_catalog_digest_duration_seconds",
                "Time spent in each phase of the data catalog digest run (work time, summed across concurrent batches — not wall-clock)",
                labelnames=["phase"],
                registry=registry,
            )
            for phase, value in [
                ("build", totals.build_duration),
                ("send", totals.send_duration),
                ("cumulative", totals.total_duration),
            ]:
                duration_gauge.labels(phase=phase).set(value)

            orgs_gauge = Gauge(
                "posthog_data_catalog_digest_orgs",
                "Org outcomes for a data catalog digest run",
                labelnames=["outcome"],
                registry=registry,
            )
            for outcome, value in [
                ("total", totals.batch_size),
                ("processed", totals.orgs_processed),
                ("skipped", totals.orgs_skipped),
                ("failed", totals.orgs_failed),
            ]:
                orgs_gauge.labels(outcome=outcome).set(value)

            emails_gauge = Gauge(
                "posthog_data_catalog_digest_emails",
                "Email outcomes for a data catalog digest run",
                labelnames=["outcome"],
                registry=registry,
            )
            for outcome, value in [
                ("sent", totals.emails_sent),
                ("skipped_optout", totals.emails_skipped_optout),
                ("skipped_no_data", totals.emails_skipped_no_data),
                ("skipped_nothing_new", totals.emails_skipped_nothing_new),
                ("failed", totals.emails_failed),
            ]:
                emails_gauge.labels(outcome=outcome).set(value)

            teams_failed_gauge = Gauge(
                "posthog_data_catalog_digest_teams_failed",
                "Projects whose pending review could not be built in a data catalog digest run",
                registry=registry,
            )
            teams_failed_gauge.set(totals.teams_failed)

            success_gauge = Gauge(
                "posthog_data_catalog_digest_success",
                "1 if the data catalog digest run completed within failure threshold, else 0",
                registry=registry,
            )
            success_gauge.set(1 if success else 0)

            failure_rate_gauge = Gauge(
                "posthog_data_catalog_digest_failure_rate",
                "Fraction of orgs whose processing raised an exception in the data catalog digest",
                registry=registry,
            )
            failure_rate_gauge.set(totals.failure_rate)

            last_run_gauge = Gauge(
                "posthog_data_catalog_digest_last_run_timestamp",
                "Unix timestamp of the most recent data catalog digest run",
                registry=registry,
            )
            last_run_gauge.set(time.time())
    except Exception as e:
        logger.warning("Failed to push data catalog digest metrics to Pushgateway", error=str(e))
        capture_exception(e)


@activity.defn(name="data-catalog-digest-push-metrics")
async def push_digest_metrics_activity(totals_dict: dict, success: bool) -> None:
    totals = DigestBatchResult(**totals_dict)
    await database_sync_to_async(_push_digest_metrics, thread_sensitive=False)(totals, success)


def _send_test_digest(email: str) -> None:
    """The recipient is the matched user's stored email, never the input string,
    so this cannot be used to redirect a team's data to an arbitrary inbox.
    """
    close_old_connections()

    if not is_email_available(with_absolute_urls=True):
        raise RuntimeError("Email is not available — check EMAIL_HOST in instance settings")

    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if not user:
        raise ValueError(f"No active user found with email {email}")

    memberships = list(OrganizationMembership.objects.select_related("organization").filter(user_id=user.id))
    if not memberships:
        raise ValueError(f"User {email} has no organization memberships")

    date_suffix = timezone.now().strftime("%Y-%W")
    sent_count = 0
    for membership in memberships:
        org = membership.organization
        teams_by_id = _project_teams(str(org.id))
        if not teams_by_id:
            continue
        reviews = build_org_pending_reviews(list(teams_by_id.values()), new_since=_new_since()).reviews
        source_teams = _source_teams(list(teams_by_id.values()))
        if not reviews and not any(source_teams.values()):
            continue
        outcome = _send_digest_for_user(
            user=user,
            org=org,
            membership=membership,
            reviews=reviews,
            teams_by_id=teams_by_id,
            date_suffix=date_suffix,
            source_teams=source_teams,
            test=True,
        )
        if outcome == DigestOutcome.SENT:
            sent_count += 1

    if sent_count == 0:
        raise ValueError(f"User {email} has no accessible projects with anything awaiting review")

    logger.info("Sent test data catalog digest", email=email, emails_sent=sent_count)


@activity.defn(name="data-catalog-digest-send-test")
async def send_test_digest(input: SendTestDigestInput) -> None:
    await database_sync_to_async(_send_test_digest, thread_sensitive=False)(input.email)
