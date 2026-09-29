"""Which sources evaluate for real, and under what workflow name.

A source's evaluation lives in that source's product, so the dispatcher starts it by name
rather than by class. The alerts product imports nothing from a source.

A source absent from this map keeps the noop evaluation path.
"""

from products.alerts.backend.facade.contracts import SourceKind

SOURCE_EVALUATION_WORKFLOWS: dict[SourceKind, str] = {
    SourceKind.LOGS: "logs-alert-evaluate",
}
