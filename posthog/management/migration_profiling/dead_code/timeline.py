"""Build per-target timelines from parsed migrations.

For dead-code detection, what matters is the **sequence of operations
against a single field / model / index across all migrations**. A
``Timeline`` makes that lookup O(1).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from posthog.management.migration_profiling.dead_code.parser import OperationNode, ParsedMigration


@dataclass
class TimelineEvent:
    app: str
    migration_name: str
    operation: OperationNode

    @property
    def class_name(self) -> str:
        return self.operation.class_name


@dataclass
class Timeline:
    """Indexed view of every operation across every migration.

    All event lists are sorted by ``(app, migration_name)`` — Django's
    ``NNNN_description`` filename convention sorts correctly under regular
    string comparison.
    """

    # (app, model, field) → events
    field_events: dict[tuple[str, str, str], list[TimelineEvent]] = field(default_factory=lambda: defaultdict(list))
    # (app, model) → events that target the model
    model_events: dict[tuple[str, str], list[TimelineEvent]] = field(default_factory=lambda: defaultdict(list))
    # (app, model, index_name) → events
    index_events: dict[tuple[str, str, str], list[TimelineEvent]] = field(default_factory=lambda: defaultdict(list))
    # All RunPython events.
    runpython_events: list[TimelineEvent] = field(default_factory=list)


def build_timeline(migrations: Iterable[ParsedMigration]) -> Timeline:
    timeline = Timeline()
    ordered = sorted(migrations, key=lambda m: (m.app, m.name))
    for m in ordered:
        for op in m.operations:
            ev = TimelineEvent(app=m.app, migration_name=m.name, operation=op)
            _index_event(timeline, ev)
    return timeline


def _index_event(timeline: Timeline, ev: TimelineEvent) -> None:
    op = ev.operation
    cn = op.class_name
    kwargs = op.kwargs

    model_name = kwargs.get("model_name") or kwargs.get("name")
    field_name = kwargs.get("name") if cn in {"AddField", "RemoveField", "AlterField"} else None
    if cn == "RenameField":
        # Track both old and new names so detectors looking at either side find it.
        old = kwargs.get("old_name")
        new = kwargs.get("new_name")
        mdl = kwargs.get("model_name")
        if mdl and old:
            timeline.field_events[(ev.app, mdl, old)].append(ev)
        if mdl and new:
            timeline.field_events[(ev.app, mdl, new)].append(ev)

    if cn in {"AddField", "RemoveField", "AlterField"} and model_name and field_name:
        timeline.field_events[(ev.app, model_name, field_name)].append(ev)

    if cn in {"CreateModel", "DeleteModel", "RenameModel"} and model_name:
        timeline.model_events[(ev.app, model_name)].append(ev)
        if cn == "RenameModel":
            new_name = kwargs.get("new_name")
            if new_name:
                timeline.model_events[(ev.app, new_name)].append(ev)

    if cn in {"AddIndex", "RemoveIndex"} and model_name:
        idx_name = kwargs.get("name")
        if idx_name:
            timeline.index_events[(ev.app, model_name, idx_name)].append(ev)

    if cn == "RunPython":
        timeline.runpython_events.append(ev)
