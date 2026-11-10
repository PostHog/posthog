from collections.abc import Collection
from enum import StrEnum
from time import perf_counter
from typing import TYPE_CHECKING, Any, Optional

import structlog
from pydantic import BaseModel

from posthog.schema import WarehouseSuggestionNote

from posthog.caching.utils import WARMING_TRIGGER_PREFIX
from posthog.clickhouse.query_tagging import Product, get_query_tag_value
from posthog.dataclasses import frozen
from posthog.query_scan.trigger import is_analyzable_principal, is_mcp_run

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User

    from products.warehouse_suggestions.backend.facade.contracts import WarehouseSuggestionNote as ContractNote

logger = structlog.get_logger(__name__)

FIELD = "warehouse_suggestions"
MAX_READ_VIEWS = 50


class SkipReason(StrEnum):
    NOT_AGENT = "not_agent"
    NO_VIEWS = "no_views"
    TOO_MANY_VIEWS = "too_many_views"
    FLAG_OFF = "flag_off"
    FAILED = "failed"


@frozen
class NotesOutcome:
    suggestion_ids: list[str] | None = None
    skipped_reason: SkipReason | None = None
    elapsed_ms: int | None = None

    def event_properties(self) -> dict[str, Any]:
        return {
            "warehouse_suggestion_ids": self.suggestion_ids,
            "warehouse_suggestions_skipped_reason": self.skipped_reason,
            "warehouse_suggestions_ms": self.elapsed_ms,
        }


def serve_warehouse_suggestions(
    team: "Team", response: BaseModel, user: Optional["User"], saved_query_ids: Collection[str], trigger: Optional[str]
) -> NotesOutcome:
    if FIELD not in type(response).model_fields or not is_analyzable_principal(user) or not _is_agent_run(trigger):
        return NotesOutcome(skipped_reason=SkipReason.NOT_AGENT)
    if not saved_query_ids:
        return NotesOutcome(skipped_reason=SkipReason.NO_VIEWS)
    if len(saved_query_ids) > MAX_READ_VIEWS:
        return NotesOutcome(skipped_reason=SkipReason.TOO_MANY_VIEWS)
    started = perf_counter()
    try:
        from products.warehouse_suggestions.backend.facade.api import suggestions_for_read_views  # noqa: PLC0415

        notes = suggestions_for_read_views(team, user, saved_query_ids, is_mcp_run=is_mcp_run())
        if notes is None:
            return NotesOutcome(skipped_reason=SkipReason.FLAG_OFF, elapsed_ms=_elapsed_ms(started))
        setattr(response, FIELD, [_schema_note(note) for note in notes])
    except Exception:
        logger.exception(
            "warehouse_suggestions_query_notes_failed", team_id=team.pk, saved_query_count=len(saved_query_ids)
        )
        return NotesOutcome(skipped_reason=SkipReason.FAILED, elapsed_ms=_elapsed_ms(started))
    return NotesOutcome(suggestion_ids=[str(note.id) for note in notes], elapsed_ms=_elapsed_ms(started))


def _schema_note(note: "ContractNote") -> WarehouseSuggestionNote:
    return WarehouseSuggestionNote(
        id=str(note.id),
        kind=note.kind.value,
        view_name=note.view_name,
        message=note.message,
        url=note.url,
        can_act=note.can_act,
    )


def _is_agent_run(trigger: Optional[str]) -> bool:
    if trigger and trigger.startswith(WARMING_TRIGGER_PREFIX):
        return False
    product = get_query_tag_value("product")
    if product == Product.ENDPOINTS:
        return False
    return is_mcp_run() or product == Product.MAX_AI


def _elapsed_ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)
