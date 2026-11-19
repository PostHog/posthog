"""Clear suspension markers that staff selected and reviewed in PostHog Admin."""

from itertools import islice

from django.contrib.admin.models import CHANGE, LogEntry
from django.db import transaction

from products.data_modeling.backend.facade.contracts import (
    SuspensionMarkerKey,
    SuspensionMarkerSummary,
    SuspensionsCleared,
    SuspensionSelection,
    SuspensionSelectionTooBroadError,
)
from products.data_modeling.backend.logic.node_suspension import unsuspend_nodes
from products.data_modeling.backend.logic.node_suspension_selection import (
    Marker,
    Selection,
    matching_suspension_markers,
)
from products.data_modeling.backend.models.node import Node

MAX_SUSPENSION_PREVIEW = 500


def _matching_markers(selection: SuspensionSelection) -> list[Marker]:
    markers = list(
        islice(
            matching_suspension_markers(
                team_id=selection.team_id,
                node_ids=list(selection.node_ids),
                saved_query_ids=list(selection.saved_query_ids),
                selection=Selection(
                    engine=selection.engine,
                    reason_contains=selection.reason_contains,
                    suspended_from=selection.suspended_from,
                    suspended_to=selection.suspended_to,
                ),
            ),
            MAX_SUSPENSION_PREVIEW + 1,
        )
    )
    if len(markers) > MAX_SUSPENSION_PREVIEW:
        raise SuspensionSelectionTooBroadError(
            f"More than {MAX_SUSPENSION_PREVIEW} suspensions match. Add filters and preview again."
        )
    return markers


def find_suspension_markers(selection: SuspensionSelection) -> list[SuspensionMarkerSummary]:
    return [
        SuspensionMarkerSummary(
            node_id=marker.node.pk,
            node_name=marker.node.name,
            team_id=marker.node.team_id,
            saved_query_id=marker.node.saved_query_id,
            engine=marker.engine,
            at=marker.at,
            reason=marker.reason,
        )
        for marker in _matching_markers(selection)
    ]


def clear_suspension_markers(
    previewed: tuple[SuspensionMarkerKey, ...], *, resumed_by: str, user_id: int
) -> SuspensionsCleared:
    # Clears the markers staff reviewed, not a new match of the selection. A marker can carry a time from before
    # the preview and still commit after it, so a time cutoff would clear a suspension nobody saw.
    nodes = Node.objects.in_bulk([key.node_id for key in previewed])
    cleared = 0
    for key in previewed:
        node = nodes.get(key.node_id)
        if node is None:
            continue
        marker = Marker(node=node, engine=key.engine, at=key.at, reason="")
        # The reset and its audit entry commit together, so a failed log write cannot leave an unaudited reset.
        with transaction.atomic():
            if unsuspend_nodes([marker.node], by=resumed_by, engine=marker.engine, only_if=marker.unchanged):
                cleared += 1
                LogEntry.objects.log_actions(
                    user_id=user_id,
                    queryset=[marker.node],
                    action_flag=CHANGE,
                    change_message=f"Cleared {marker.engine} suspension. By / note: {resumed_by}",
                    single_object=True,
                )
    return SuspensionsCleared(cleared=cleared, skipped=len(previewed) - cleared)
