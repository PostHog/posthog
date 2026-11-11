"""Give older Slack insight-alert destinations the chart block that new ones get.

A destination keeps its own copy of the Slack blocks, taken from the sub-template at the moment
somebody created it. Destinations created before the chart shipped therefore still post the plain
divider that the chart block replaced, and no amount of alert firing changes that on its own.

The rewrite swaps that one divider and leaves everything else as it was. A destination whose
blocks no longer match the shape the sub-template produced is treated as hand-edited and skipped,
so nobody's customized message is overwritten.
"""

import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet

import structlog

from posthog.dataclasses import frozen
from posthog.plugins.plugin_server_api import reload_hog_functions_on_workers
from posthog.tasks.alerts.utils import INSIGHT_ALERT_FIRING_EVENT

from products.alerts.backend.logic.destination_eligibility import STOCK_INPUT_VALUES
from products.alerts.backend.logic.insight_alert_destinations import (
    INSIGHT_CHART_BLOCK,
    SLACK_TEMPLATE_ID,
    hog_slack_attachments,
    hog_slack_blocks,
)
from products.cdp.backend.facade.models import HogFunction, HogFunctionTemplate
from products.cdp.backend.validation import compile_hog, generate_template_bytecode

logger = structlog.get_logger(__name__)

DIVIDER_BLOCK = {"type": "divider"}


@frozen
class ChartBlockBackfill:
    scanned: int
    repaired: int
    already_current: int
    left_alone: int
    uncompilable: int


def insight_alert_slack_destinations(team_ids: Sequence[int] | None = None) -> QuerySet[HogFunction]:
    destinations = HogFunction.objects.filter(
        deleted=False,
        template_id=SLACK_TEMPLATE_ID,
        filters__events__contains=[{"id": INSIGHT_ALERT_FIRING_EVENT, "type": "events"}],
    ).order_by("team_id", "id")
    if team_ids is not None:
        destinations = destinations.filter(team_id__in=team_ids)
    return destinations


def mentions_chart(blocks: Any) -> bool:
    """Whether these blocks already do something with the chart, however they came by it."""
    return "insight_chart_url" in json.dumps(blocks, default=str)


def blocks_with_chart(blocks: Any) -> list[Any] | None:
    """The blocks with the chart in place of the divider, or None when this destination is not one
    the sub-template produced and so is not ours to rewrite."""
    if not isinstance(blocks, list) or mentions_chart(blocks):
        return None
    actions_index = next(
        (index for index, block in enumerate(blocks) if isinstance(block, dict) and block.get("type") == "actions"),
        None,
    )
    # The divider only ever sat directly above the buttons. Anywhere else it is somebody's own.
    if actions_index is None or actions_index == 0 or blocks[actions_index - 1] != DIVIDER_BLOCK:
        return None
    return [*blocks[: actions_index - 1], INSIGHT_CHART_BLOCK, *blocks[actions_index:]]


def blocks_with_readable_message(blocks: Any) -> list[Any] | None:
    if blocks != hog_slack_blocks() and blocks not in STOCK_INPUT_VALUES[SLACK_TEMPLATE_ID]["blocks"]:
        return None
    return hog_slack_blocks()


def backfill_insight_alert_chart_blocks(
    *,
    team_ids: Sequence[int] | None = None,
    limit: int | None = None,
    batch_size: int = 100,
    apply: bool = False,
    format_messages: bool = False,
) -> ChartBlockBackfill:
    template = HogFunctionTemplate.get_template(SLACK_TEMPLATE_ID) if format_messages else None
    known_codes: set[str] = set()
    if format_messages:
        if template is None or not any(item.get("key") == "attachments" for item in template.inputs_schema):
            raise ValueError("Sync Slack templates before updating alert message formatting.")
        known_codes = set(
            HogFunctionTemplate.objects.filter(template_id=SLACK_TEMPLATE_ID).values_list("code", flat=True)
        )
    destinations = insight_alert_slack_destinations(team_ids)
    if limit is not None:
        destinations = destinations[:limit]

    scanned = already_current = left_alone = uncompilable = 0
    repaired: list[HogFunction] = []
    ids_by_team: dict[int, list[UUID]] = {}

    for destination in destinations:
        scanned += 1
        raw_blocks_input = (destination.inputs or {}).get("blocks")
        blocks_input: dict[str, Any] = raw_blocks_input if isinstance(raw_blocks_input, dict) else {}
        blocks = blocks_input.get("value")

        if (
            format_messages
            and template is not None
            and blocks == []
            and ((destination.inputs or {}).get("attachments") or {}).get("value") == hog_slack_attachments()
            and destination.hog == template.code
        ) or (not format_messages and mentions_chart(destination.inputs)):
            already_current += 1
            continue

        # Liquid blocks are rendered by the worker rather than compiled, so the hog expression the
        # chart block is written in would reach Slack as literal text.
        is_hog_templated = blocks_input.get("templating", "hog") == "hog"
        upgrade = blocks_with_readable_message if format_messages else blocks_with_chart
        upgraded = upgrade(blocks) if is_hog_templated else None
        if format_messages:
            text_input = (destination.inputs or {}).get("text", {})
            attachments_input = (destination.inputs or {}).get("attachments", {})
            stock_text = (
                isinstance(text_input, dict)
                and text_input.get("templating", "hog") == "hog"
                and text_input.get("value") in [None, "", *STOCK_INPUT_VALUES[SLACK_TEMPLATE_ID]["text"]]
            )
            no_attachments = isinstance(attachments_input, dict) and attachments_input.get("value") in (None, [])
            if destination.hog not in known_codes or not stock_text or not no_attachments:
                upgraded = None
        if upgraded is None:
            left_alone += 1
            logger.info(
                "Leaving Slack insight-alert blocks alone",
                team_id=destination.team_id,
                hog_function_id=str(destination.id),
                templating=blocks_input.get("templating"),
            )
            continue

        try:
            # The worker renders the stored bytecode, not the value, so a value written without a
            # matching recompile would keep posting the old blocks.
            bytecode = generate_template_bytecode(upgraded, set(), function_type=destination.type)
            attachments = hog_slack_attachments() if format_messages else []
            attachment_bytecode = generate_template_bytecode(attachments, set(), function_type=destination.type)
            sender_bytecode = compile_hog(template.code, "internal_destination") if template is not None else None
        except Exception:
            # Recompiling covers the whole block list, so an edit elsewhere in it that the compiler
            # now rejects lands here. One destination must not stop the sweep.
            uncompilable += 1
            logger.exception(
                "Could not recompile Slack insight-alert blocks",
                team_id=destination.team_id,
                hog_function_id=str(destination.id),
            )
            continue

        destination.inputs = {
            **(destination.inputs or {}),
            "blocks": {**blocks_input, "value": upgraded, "bytecode": bytecode},
        }
        if format_messages and template is not None:
            destination.inputs["blocks"] = {"value": []}
            destination.inputs["text"] = {"value": ""}
            destination.inputs["attachments"] = {
                "value": attachments,
                "bytecode": attachment_bytecode,
            }
            destination.hog = template.code
            destination.bytecode = sender_bytecode
            destination.inputs_schema = [
                item for item in (destination.inputs_schema or []) if item.get("key") != "attachments"
            ] + [item for item in template.inputs_schema if item.get("key") == "attachments"]
        repaired.append(destination)
        ids_by_team.setdefault(destination.team_id, []).append(destination.id)

    if apply and repaired:
        with transaction.atomic():
            HogFunction.objects.bulk_update(
                repaired,
                ["inputs", "hog", "bytecode", "inputs_schema"] if format_messages else ["inputs"],
                batch_size=batch_size,
            )
            for team_id, hog_function_ids in ids_by_team.items():
                # bulk_update skips post_save, so the running workers need telling by hand.
                _reload_after_commit(team_id=team_id, hog_function_ids=hog_function_ids)

    return ChartBlockBackfill(
        scanned=scanned,
        repaired=len(repaired),
        already_current=already_current,
        left_alone=left_alone,
        uncompilable=uncompilable,
    )


def _reload_after_commit(*, team_id: int, hog_function_ids: Sequence[UUID]) -> None:
    serialized_ids = sorted(str(hog_function_id) for hog_function_id in hog_function_ids)
    transaction.on_commit(
        lambda: reload_hog_functions_on_workers(team_id=team_id, hog_function_ids=serialized_ids),
        robust=True,
    )
