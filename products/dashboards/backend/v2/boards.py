"""Saved `dashboard-v2` boards: one row per board, holding the whole document.

Validation is permissive on purpose. A save is refused only when the document is not at a schema version this code
can read, or is over `MAX_BOARD_SPEC_BYTES`. The scene validates each tile when it renders, so a broken tile still
saves and shows as an error tile instead of blocking the whole board.
"""

from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Q

from posthog.paging import Page, PageRequest

from products.dashboards.backend.facade.contracts import (
    BoardDetail,
    BoardListAccess,
    BoardNotFound,
    BoardReadOnly,
    BoardSpecInvalid,
    BoardSummary,
    BoardVersionConflict,
)
from products.dashboards.backend.facade.enums import BoardManagedBy
from products.dashboards.backend.models.dashboard_v2_board import DashboardV2Board
from products.dashboards.backend.v2.board_schema import (
    check_size,
    check_storable,
    folder_of,
    tags_of,
    title_of,
    upgrade,
)


def _live(team_id: int):
    return DashboardV2Board.objects.for_team(team_id).filter(deleted=False)


def _summary_fields(board: DashboardV2Board) -> dict[str, Any]:
    return {
        "id": board.id,
        "team_id": board.team_id,
        "uid": board.uid,
        "title": board.title,
        "tags": board.tags,
        "folder": board.folder,
        "version": board.version,
        "managed_by": BoardManagedBy(board.managed_by),
        "template_id": board.template_id,
        "template_version": board.template_version,
        "created_at": board.created_at,
        "created_by_id": board.created_by_id,
        "last_modified_at": board.last_modified_at,
        "last_modified_by_id": board.last_modified_by_id,
    }


def _detail(board: DashboardV2Board) -> BoardDetail:
    # A row saved before a schema upgrade existed is upgraded here, on every read, until it is next saved.
    try:
        spec = upgrade(board.spec)
    except BoardSpecInvalid:
        # Saved by a newer release that was rolled back. The client shows what it can of it.
        spec = board.spec
    return BoardDetail(**_summary_fields(board), spec=spec)


def _prepare(spec: dict[str, Any]) -> dict[str, Any]:
    # Before anything serializes the document, which recurses once per level of nesting.
    check_storable(spec)
    spec = upgrade(spec)
    check_size(spec)
    return spec


def _row_ids(ids: frozenset[str]) -> list[UUID]:
    # Rules under the `dashboard` resource also name classic dashboards by integer id. Those are not boards.
    row_ids = []
    for value in ids:
        try:
            row_ids.append(UUID(value))
        except ValueError:
            continue
    return row_ids


def list_boards(team_id: int, page: PageRequest, access: BoardListAccess | None) -> Page[BoardSummary]:
    rows = _live(team_id).defer("spec").order_by("-last_modified_at")
    if access is not None:
        own = Q(created_by_id=access.viewer_id)
        if access.only_allowed:
            rows = rows.filter(Q(id__in=_row_ids(access.allowed_ids)) | own)
        elif access.blocked_ids:
            rows = rows.exclude(Q(id__in=_row_ids(access.blocked_ids)) & ~own)
    count = rows.count()
    results = [BoardSummary(**_summary_fields(row)) for row in rows[page.offset : page.offset + page.limit]]
    return Page(results=results, count=count)


def get_board(team_id: int, uid: str) -> BoardDetail:
    board = _live(team_id).filter(uid=uid).first()
    if board is None:
        raise BoardNotFound(uid)
    return _detail(board)


def create_board(team_id: int, user_id: int, spec: dict[str, Any]) -> BoardDetail:
    spec = _prepare(spec)
    board = DashboardV2Board.objects.for_team(team_id).create(
        team_id=team_id,
        spec=spec,
        title=title_of(spec),
        tags=tags_of(spec),
        folder=folder_of(spec),
        created_by_id=user_id,
        last_modified_by_id=user_id,
    )
    return _detail(board)


def update_board(team_id: int, uid: str, user_id: int, spec: dict[str, Any], base_version: int | None) -> BoardDetail:
    spec = _prepare(spec)
    with transaction.atomic():
        board = _live(team_id).select_for_update().filter(uid=uid).first()
        if board is None:
            raise BoardNotFound(uid)
        if board.managed_by != BoardManagedBy.NATIVE:
            raise BoardReadOnly(uid)
        if base_version is not None and board.version != base_version:
            raise BoardVersionConflict(current_version=board.version, base_version=base_version)
        board.spec = spec
        board.title = title_of(spec)
        board.tags = tags_of(spec)
        board.folder = folder_of(spec)
        # The row is locked, so no other save can move the version between this read and the write.
        board.version += 1
        board.last_modified_by_id = user_id
        board.save(update_fields=["spec", "title", "tags", "folder", "version", "last_modified_by", "last_modified_at"])
    return _detail(board)


def delete_board(team_id: int, uid: str, user_id: int) -> None:
    with transaction.atomic():
        board = _live(team_id).select_for_update().filter(uid=uid).first()
        if board is None:
            raise BoardNotFound(uid)
        if board.managed_by != BoardManagedBy.NATIVE:
            raise BoardReadOnly(uid)
        board.deleted = True
        board.last_modified_by_id = user_id
        board.save(update_fields=["deleted", "last_modified_by", "last_modified_at"])
