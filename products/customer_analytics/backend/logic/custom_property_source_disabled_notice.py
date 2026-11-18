from datetime import datetime, time, timedelta
from hashlib import sha256
from uuid import NAMESPACE_URL, UUID, uuid5

from django.db import connection, transaction
from django.utils import timezone

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.models.team.team import DEPRECATED_ATTRS
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
CONFIGURATION_ACCOUNTS_PATH = "/customer_analytics/configuration?tab=customer-analytics-accounts"
DISABLED_BODY = (
    "PostHog disabled this sync after five consecutive failures. Review the latest run, fix the "
    "source, then re-enable the sync."
)


def notify_source_auto_disabled(*, team_id: int, source_id: UUID, disable_event_id: str) -> None:
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

        team = (
            Team.objects.select_related("parent_team")
            .defer(*(f"parent_team__{attr}" for attr in DEPRECATED_ATTRS))
            .filter(id=team_id)
            .first()
        )
        if team is None:
            log.info("custom_property_source_disabled.team_gone")
            return

        access = UserAccessControl(user=owner, team=team, organization_id=str(team.organization_id))
        if not access.has_project_access:
            log.info("custom_property_source_disabled.owner_without_project_access")
            return

        name = source.definition.name
        _notify_owner(team=team, owner=owner, source=source, name=name, disable_event_id=disable_event_id, log=log)
        _open_owner_task(team=team, owner=owner, source=source, name=name, disable_event_id=disable_event_id, log=log)
    except Exception as error:
        capture_exception(error)
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
                source_id=str(source.id),
                idempotency_key=_notification_idempotency_key(source.id, disable_event_id),
            )
        )
    except Exception as error:
        capture_exception(error)
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
    try:
        if not posthog_feature_flag_enabled(
            CUSTOMER_ANALYTICS_CUSTOMER_TASKS_FLAG,
            str(owner.distinct_id),
            organization_id=team.organization_id,
            team_id=team.id,
        ):
            log.info("custom_property_source_disabled.tasks_unavailable")
            return

        canonical_team = team.parent_team or team
        access = UserAccessControl(
            user=owner,
            team=canonical_team,
            organization_id=str(canonical_team.organization_id),
        )
        if not access.has_project_access or not access.check_access_level_for_resource("customer_task", "editor"):
            log.info("custom_property_source_disabled.tasks_unavailable")
            return

        task_id = _task_id(team_id=canonical_team.id, source_id=source.id, disable_event_id=disable_event_id)
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", [canonical_team.id, str(task_id)])
            if CustomerTask.objects.for_team(canonical_team.id).filter(id=task_id).exists():
                return
            create_customer_task(
                team=canonical_team,
                input=CreateCustomerTaskInput(
                    name=f"Fix warehouse property sync: {name}"[:TASK_NAME_MAX_LENGTH],
                    description=DISABLED_BODY,
                    assigned_to_id=owner.id,
                    due_at=_end_of_next_business_day(team),
                ),
                actor=None,
                user_access_control=access,
                task_id=task_id,
            )
    except Exception as error:
        capture_exception(error)
        log.exception("custom_property_source_disabled.task_failed")


def _notification_idempotency_key(source_id: UUID, disable_event_id: str) -> str:
    event_hash = sha256(disable_event_id.encode()).hexdigest()[:32]
    return f"custom-property-source:{source_id}:disabled:{event_hash}"


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
