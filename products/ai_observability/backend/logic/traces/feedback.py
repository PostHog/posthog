import json
from collections.abc import Sequence
from datetime import datetime

from posthog.dataclasses import frozen

from .node_ids import NodeIdResolver, NodeIds
from .trace_queries import FEEDBACK_EVENT, METRIC_EVENT, NODE_EVENT_NAMES, FeedbackEventRow


def present_value(raw_json: str) -> str | None:
    """A sent value as text, or None when the value is missing, null or an empty string. 0 and false are present."""
    if not raw_json:
        return None
    try:
        value = json.loads(raw_json)
    except ValueError:
        return None
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"))


@frozen
class Score:
    id: str
    name: str | None
    value: str
    node_id: str
    timestamp: datetime


@frozen
class FeedbackText:
    id: str
    text: str
    node_id: str
    timestamp: datetime


class TraceFeedback:
    def __init__(self, trace_id: str, rows: Sequence[FeedbackEventRow]) -> None:
        ordered = sorted(rows, key=lambda row: row.timestamp)
        steps = NodeIdResolver(
            NodeIds(uuid=row.uuid, generation_id=row.generation_id, span_id=row.span_id)
            for row in ordered
            if row.event in NODE_EVENT_NAMES
        )

        def target(row: FeedbackEventRow) -> str:
            if row.parent_id is None or row.parent_id == trace_id:
                return trace_id
            return steps.resolve(row.parent_id) or trace_id

        scores: list[Score] = []
        texts: list[FeedbackText] = []
        for row in ordered:
            if row.event == METRIC_EVENT and (value := present_value(row.metric_value_json)) is not None:
                scores.append(
                    Score(id=row.uuid, name=row.metric_name, value=value, node_id=target(row), timestamp=row.timestamp)
                )
            elif row.event == FEEDBACK_EVENT and (text := present_value(row.feedback_text_json)) is not None:
                texts.append(FeedbackText(id=row.uuid, text=text, node_id=target(row), timestamp=row.timestamp))
        self.scores = tuple(scores)
        self.texts = tuple(texts)
