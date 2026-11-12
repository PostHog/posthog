from datetime import datetime

from posthog.dataclasses import frozen

from ..message_normalizer.values import Value
from .node import NodeEvent


@frozen
class StepDatasetItem:
    trace_id: str
    trace_timestamp: datetime
    event: NodeEvent | None

    @property
    def is_root(self) -> bool:
        return self.event is None or self.event.kind == "trace"

    @property
    def source_event_id(self) -> str:
        return self.trace_id if self.event is None or self.is_root else self.event.row.uuid

    @property
    def input(self) -> Value:
        value = self.event.input if self.event else None
        return {} if value is None else value

    @property
    def source_output(self) -> Value:
        return self.event.output if self.event else None

    @property
    def metadata(self) -> dict[str, Value]:
        return {} if self.is_root or self.event is None else self.event.custom_properties
