"""Telling the sync owner that PostHog disabled their warehouse property sync.

A disabled source is silent: the properties it feeds — flag targeting, cohorts, insight filters —
keep serving the last values it wrote, and until now the history page was the only place the
disablement showed up. The owner is ``CustomPropertySource.created_by``, the person who bound the
warehouse column in the first place.

Both branches run after the source transaction commits and each guards itself, so a project
without customer tasks still gets the notification, and a delivery that fails leaves the
auto-disable in place.
"""

from datetime import datetime, time, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from django.db import connection, transaction
from django.utils import timezone

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.permissions import posthog_feature_flag_enabled

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.customer_analytics.backend.constants import CUSTOMER_ANALYTICS_CUSTOMER_TASKS_FLAG
from products.customer_analytics.backend.facade.contracts import CreateCustomerTaskInput
from products.customer_analytics.backend.logic.customer_tasks import create_customer_task
from products.customer_analytics.backend.models import CustomerTask, CustomPropertySource
from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    SourceType,
    TargetType,
    create_notification,
)
from products.notifications.backend.facade.enums import NotificationOnlyResourceType

logger = structlog.get_logger(__name__)

TITLE_MAX_LENGTH = 255
TASK_NAME_MAX_LENGTH = 400

# The accounts tab of Customer analytics configuration, where custom property sources are listed.
# Project-relative: the notifications panel adds the project prefix on navigation.
CONFIGURATION_ACCOUNTS_PATH = "/customer_analytics/configuration?tab=customer-analytics-accounts"

# No raw warehouse error here. It can carry a host name or a fragment of a row, and the owner sees
# the real one on the run once they open configuration.
DISABLED_BODY = (
    "PostHog disabled this sync after five consecutive failures. Review the latest run, fix the "
    "source, then re-enable the sync."
)


def notify_source_auto_disabled(*, team_id: int, source_id: UUID, disable_event_id: str) -> None:
    """Notify the sync owner and open a task for them. Never raises."""
    log = logger.bind(team_id=team_id, source_id=str(source_id), disable_event_id=disable_event_id)
    try:
        source = (
            CustomPropertySource.objects.for_team(team_id)
            .select_related("definition", "created_by")
            .filter(id=source_id)
            .first()
        )
        if source is None:
            log.info("custom_property_source_disabled.source_gone")
            return

        owner = source.created_by
        if owner is None or not owner.is_active:
            log.info("custom_property_source_disabled.owner_unavailable")
            return

        team = Team.objects.filter(id=team_id).first()
        if team is None:
            log.info("custom_property_source_disabled.team_gone")
            return

        access = UserAccessControl(user=owner, team=team)
        if not access.has_project_access:
            log.info("custom_property_source_disabled.owner_without_project_access")
            return

        name = source.definition.name
        _notify_owner(team=team, owner=owner, source=source, name=name, disable_event_id=disable_event_id, log=log)
        _open_owner_task(team=team, owner=owner, source=source, name=name, disable_event_id=disable_event_id, log=log)
    except Exception as e:
        capture_exception(e)
        log.exception("custom_property_source_disabled.dispatch_failed")


def _notify_owner(
    *,
    team: Team,
    owner: User,
    source: CustomPropertySource,
    name: str,
    disable_event_id: str,
    log: structlog.BoundLogger,
) -> None:
    try:
        create_notification(
            NotificationData(
                team_id=team.id,
                notification_type=NotificationType.PIPELINE_FAILURE,
                priority=Priority.NORMAL,
                title=f"Warehouse property sync disabled: {name}"[:TITLE_MAX_LENGTH],
                body=DISABLED_BODY,
                target_type=TargetType.USER,
                target_id=str(owner.id),
                resource_type=NotificationOnlyResourceType.PIPELINE,
                resource_id=str(source.id),
                source_url=CONFIGURATION_ACCOUNTS_PATH,
                source_type=SourceType.CUSTOMER_ANALYTICS,
                source_id=disable_event_id,
                # A unique constraint, so two recorders racing on the same disablement still send
                # one notification. The run id is part of the key, so a later disablement after
                # someone re-enables the source sends a fresh one.
                idempotency_key=f"custom-property-source-disabled-{source.id}-{disable_event_id}",
            )
        )
    except Exception as e:
        capture_exception(e)
        log.exception("custom_property_source_disabled.notification_failed")


def _open_owner_task(
    *,
    team: Team,
    owner: User,
    source: CustomPropertySource,
    name: str,
    disable_event_id: str,
    log: structlog.BoundLogger,
) -> None:
    # Tasks live on the project, not the environment the sync ran in.
    canonical_team = team.parent_team or team
    if not posthog_feature_flag_enabled(
        CUSTOMER_ANALYTICS_CUSTOMER_TASKS_FLAG,
        str(owner.distinct_id),
        organization_id=team.organization_id,
        team_id=team.id,
    ):
        # A task nobody can open is worse than no task: it never leaves the owner's list.
        log.info("custom_property_source_disabled.tasks_unavailable")
        return

    task_id = _task_id(team_id=canonical_team.id, source_id=source.id, disable_event_id=disable_event_id)
    try:
        with transaction.atomic():
            # Lock the disablement before its task exists, so two racing deliveries create one
            # task, one activity row and one access grant.
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", [canonical_team.id, str(task_id)])
            if CustomerTask.objects.for_team(canonical_team.id).filter(id=task_id).exists():
                return
            create_customer_task(
                team=canonical_team,
                input=CreateCustomerTaskInput(
                    # No account: one source can feed properties across every account and person.
                    name=f"Fix warehouse property sync: {name}"[:TASK_NAME_MAX_LENGTH],
                    description=DISABLED_BODY,
                    assigned_to_id=owner.id,
                    due_at=_end_of_next_business_day(canonical_team),
                ),
                # PostHog disabled the sync, so no user owns the action.
                actor=None,
                user_access_control=UserAccessControl(user=owner, team=canonical_team),
                task_id=task_id,
            )
    except Exception as e:
        capture_exception(e)
        log.exception("custom_property_source_disabled.task_failed")


def _task_id(*, team_id: int, source_id: UUID, disable_event_id: str) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"posthog:customer-task:{team_id}:custom-property-source-disabled:{source_id}:{disable_event_id}",
    )


def _end_of_next_business_day(team: Team) -> datetime:
    tz = team.timezone_info
    day = timezone.now().astimezone(tz).date() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return datetime.combine(day, time(23, 59, 59), tzinfo=tz)
