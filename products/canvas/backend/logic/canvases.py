"""Canvas records: list, read, create, update, delete, and the home canvas."""

from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

import structlog

from posthog.models.user import User

from products.canvas.backend.facade.contracts import (
    CanvasAccessDeniedError,
    CanvasFieldChange,
    CanvasNotFoundError,
    CanvasRecord,
    CanvasUpdateResult,
    CanvasViewer,
)
from products.canvas.backend.facade.enums import CanvasAccess
from products.canvas.backend.logic.access import authorized_canvases
from products.canvas.backend.logic.records import canvas_record
from products.canvas.backend.models import Canvas, CanvasHomePreference
from products.canvas.backend.welcome import seed_home_canvas

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import AccessControlLevel, UserAccessControl

logger = structlog.get_logger(__name__)

# Every field a canvas record reads, so one query loads the record.
_RECORD_RELATIONS = ("created_by", "current_source_version")


def user_or_none(user_id: int | None) -> User | None:
    return User.objects.filter(id=user_id).first() if user_id is not None else None


def canvas_row(team_id: int, canvas_id: UUID | str) -> Canvas:
    """One canvas of the team, for an operation the access check already allowed."""
    return Canvas.objects.unscoped().select_related(*_RECORD_RELATIONS).get(team_id=team_id, id=canvas_id)


def check_object_access(
    canvas: Canvas, user_access_control: "UserAccessControl | None", required_level: str | None
) -> None:
    """The object-level access-control check that `get_object` runs for a model viewset."""
    if user_access_control is None or required_level is None:
        return
    if not user_access_control.check_access_level_for_object(
        canvas, required_level=cast("AccessControlLevel", required_level)
    ):
        raise CanvasAccessDeniedError(required_level)


def _listing(
    viewer: CanvasViewer,
    *,
    channel_id: str | None,
    kind: str | None,
    search: str | None,
    user_access_control: "UserAccessControl | None",
    include_all_if_admin: bool,
) -> QuerySet[Canvas]:
    queryset = authorized_canvases(viewer, CanvasAccess.READ)
    if user_access_control is not None:
        queryset = user_access_control.filter_queryset_by_access_level(
            queryset, include_all_if_admin=include_all_if_admin
        )
    if channel_id:
        try:
            channel_id = str(UUID(channel_id))
        except ValueError:
            return queryset.none()
        queryset = queryset.filter(channel_id=channel_id)
    if kind:
        if kind not in Canvas.KINDS:
            return queryset.none()
        queryset = queryset.filter(kind=kind)
    if search:
        queryset = queryset.filter(Q(name__icontains=search) | Q(description__icontains=search))
    return queryset


def count_canvases(
    viewer: CanvasViewer,
    *,
    channel_id: str | None,
    kind: str | None,
    search: str | None,
    user_access_control: "UserAccessControl | None",
    include_all_if_admin: bool,
) -> int:
    return _listing(
        viewer,
        channel_id=channel_id,
        kind=kind,
        search=search,
        user_access_control=user_access_control,
        include_all_if_admin=include_all_if_admin,
    ).count()


def list_canvases(
    viewer: CanvasViewer,
    *,
    channel_id: str | None,
    kind: str | None,
    search: str | None,
    user_access_control: "UserAccessControl | None",
    include_all_if_admin: bool,
    offset: int,
    limit: int,
) -> list[CanvasRecord]:
    rows = _listing(
        viewer,
        channel_id=channel_id,
        kind=kind,
        search=search,
        user_access_control=user_access_control,
        include_all_if_admin=include_all_if_admin,
    ).select_related(*_RECORD_RELATIONS)
    return [canvas_record(canvas) for canvas in rows[offset : offset + limit]]


def get_canvas(
    viewer: CanvasViewer,
    access: CanvasAccess,
    canvas_id: UUID | str,
    *,
    user_access_control: "UserAccessControl | None",
    required_level: str | None,
) -> CanvasRecord:
    """The canvas, or CanvasNotFoundError when `access` cannot reach it, or CanvasAccessDeniedError."""
    try:
        canvas = authorized_canvases(viewer, access).select_related(*_RECORD_RELATIONS).filter(id=canvas_id).first()
    except (ValueError, ValidationError):
        canvas = None
    if canvas is None:
        raise CanvasNotFoundError
    check_object_access(canvas, user_access_control, required_level)
    return canvas_record(canvas)


def create_canvas(
    *,
    team_id: int,
    user_id: int | None,
    channel_id: UUID,
    name: str,
    kind: str,
    description: str,
    template_id: str,
    generation_task_id: UUID | None,
) -> CanvasRecord:
    canvas = Canvas.objects.create(
        team_id=team_id,
        channel_id=channel_id,
        name=name,
        kind=kind,
        description=description,
        template_id=template_id,
        created_by=user_or_none(user_id),
        generation_task_id=generation_task_id,
    )
    return canvas_record(canvas)


def update_canvas(team_id: int, canvas_id: UUID, changes: dict[str, Any]) -> CanvasUpdateResult:
    """Apply validated metadata changes: name, description, channel_id, pinned, generation_task_id."""
    canvas = canvas_row(team_id, canvas_id)
    update_fields = ["updated_at"]
    recorded: list[CanvasFieldChange] = []

    def record(field: str, before: Any = None, after: Any = None) -> None:
        recorded.append(CanvasFieldChange(field=field, before=before, after=after))

    if "name" in changes:
        if changes["name"] != canvas.name:
            record("name", canvas.name, changes["name"])
        canvas.name = changes["name"]
        update_fields.append("name")
    if "description" in changes:
        if changes["description"] != canvas.description:
            record("description", canvas.description, changes["description"])
        canvas.description = changes["description"]
        update_fields.append("description")
    if "channel_id" in changes:
        channel_id = changes["channel_id"]
        if channel_id != canvas.channel_id:
            record("channel", str(canvas.channel_id), str(channel_id))
            if canvas.pinned_at is not None:
                record("pinned", True, False)
                canvas.pinned_at = None
                update_fields.append("pinned_at")
        canvas.channel_id = channel_id
        update_fields.append("channel_id")
    if "pinned" in changes:
        was_pinned = canvas.pinned_at is not None
        if changes["pinned"] != was_pinned:
            record("pinned", was_pinned, changes["pinned"])
        canvas.pinned_at = timezone.now() if changes["pinned"] else None
        update_fields.append("pinned_at")
    if "generation_task_id" in changes:
        canvas.generation_task_id = changes["generation_task_id"]
        update_fields.append("generation_task_id")
    canvas.save(update_fields=update_fields)
    return CanvasUpdateResult(canvas=canvas_record(canvas), changes=recorded)


def delete_canvas(team_id: int, canvas_id: UUID) -> CanvasRecord:
    canvas = canvas_row(team_id, canvas_id)
    canvas.deleted = True
    canvas.save(update_fields=["deleted", "updated_at"])
    return canvas_record(canvas)


def home_canvas(team_id: int, user_id: int) -> CanvasRecord | None:
    canvas = _home_canvas_for(team_id, user_id)
    return canvas_record(canvas) if canvas is not None else None


def provision_home_canvas(team_id: int, user_id: int, channel_id: UUID) -> tuple[CanvasRecord, bool]:
    """The user's home canvas, created in `channel_id` when there is none. The bool is True on create."""
    user = User.objects.get(id=user_id)
    with transaction.atomic():
        # Serialize provisioning per user: two concurrent first-opens (two
        # tabs, or desktop plus web) would otherwise both miss the unlocked read
        # and each create a "Home" canvas, leaving one orphaned. Re-read under
        # the lock so the loser returns the winner's canvas instead.
        _lock_home_provisioning(team_id, user_id)
        existing = _home_canvas_for(team_id, user_id)
        if existing is not None:
            return canvas_record(existing), False
        canvas = Canvas.objects.create(
            team_id=team_id,
            channel_id=channel_id,
            name="Home",
            kind=Canvas.KIND_GRID,
            description="Your personal home canvas.",
            created_by=user,
        )
        CanvasHomePreference.objects.for_team(team_id).update_or_create(
            team_id=team_id, user=user, defaults={"canvas": canvas}
        )
    # Starter content is best-effort: an empty home still provisions when
    # object storage or the seed publish is unavailable.
    try:
        seed_home_canvas(canvas, user=user, channel_id=channel_id)
    except Exception:
        logger.exception("Failed to seed home canvas", canvas_id=str(canvas.id), team_id=team_id)
    # Seeding publishes through its own canvas instance, so read the row again for the new head.
    return canvas_record(canvas_row(team_id, canvas.id)), True


def _lock_home_provisioning(team_id: int, user_id: int) -> None:
    """Serialize home provisioning for one user inside the current transaction.

    There is no preference row to lock before the first provision, so a
    transaction-scoped advisory lock guards the read-then-create window.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"canvas_home:{team_id}:{user_id}"],
        )


def _home_canvas_for(team_id: int, user_id: int) -> Canvas | None:
    """The user's home canvas, or None when there is none to open.

    Deleting a canvas is a soft delete that leaves the pointer behind, so a
    pointer at a deleted canvas means "no home set", not a broken home.
    """
    preference = (
        CanvasHomePreference.objects.for_team(team_id)
        .select_related(*(f"canvas__{relation}" for relation in _RECORD_RELATIONS))
        .filter(user_id=user_id)
        .first()
    )
    if preference is None or preference.canvas.deleted:
        return None
    return preference.canvas
