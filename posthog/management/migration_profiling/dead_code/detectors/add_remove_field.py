"""Detector A — find AddField → RemoveField pairs on the same field.

A column that was added in one migration and removed in a later one is a
net-zero schema change. Both migrations (plus any intermediate ``AlterField``)
can be folded out of a squash without changing the resulting schema.

Confidence is high when:

- The field name isn't re-introduced after the RemoveField (no later AddField
  for the same target).
- Only ``AlterField`` ops sit between the AddField and RemoveField — those
  rewrite the column shape but the column is about to be dropped anyway.

Confidence drops when:

- A ``RunPython`` op sits between them — that op might have produced
  externally-visible data side effects (kafka messages, audit log rows, etc.)
  even though the column itself is going away. Worth a manual look.
- The field name reappears later — the field was added back, the original
  drop is "real history", not dead.
"""

from __future__ import annotations

from collections.abc import Iterable

from posthog.management.migration_profiling.dead_code.detector_base import AnalysisContext, Detector
from posthog.management.migration_profiling.dead_code.models import Finding
from posthog.management.migration_profiling.dead_code.timeline import TimelineEvent

CONFIDENCE_CLEAN_PAIR = 0.95
CONFIDENCE_WITH_ALTERS = 0.90
CONFIDENCE_WITH_RUNPYTHON_NEARBY = 0.60


class AddRemoveFieldDetector(Detector):
    name = "add_remove_field_loop"
    description = "Fields that were added then later removed — both migrations are net-zero."

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        for (app, model, field), events in ctx.timeline.field_events.items():
            yield from self._scan_field(app, model, field, events, ctx)

    def _scan_field(
        self,
        app: str,
        model: str,
        field: str,
        events: list[TimelineEvent],
        ctx: AnalysisContext,
    ) -> Iterable[Finding]:
        """Walk a single (app, model, field) timeline looking for Add→Remove pairs.

        Pairs are reported per add/remove cycle, so a field that was added,
        removed, added again, and removed again would produce two findings.
        """
        ordered = sorted(events, key=lambda e: e.migration_name)
        i = 0
        while i < len(ordered):
            ev = ordered[i]
            if ev.class_name != "AddField":
                i += 1
                continue
            # Find the next RemoveField for the same field, with no intervening
            # AddField (which would mean the field was re-added — different story).
            for j in range(i + 1, len(ordered)):
                later = ordered[j]
                if later.class_name == "AddField":
                    # Field was re-added; bail on this pair and continue from here.
                    i = j
                    break
                if later.class_name == "RemoveField":
                    yield self._build_finding(app, model, field, ordered[i : j + 1], ctx)
                    i = j + 1
                    break
            else:
                # No matching RemoveField found.
                i += 1

    def _build_finding(
        self,
        app: str,
        model: str,
        field: str,
        chain: list[TimelineEvent],
        ctx: AnalysisContext,
    ) -> Finding:
        add_ev = chain[0]
        remove_ev = chain[-1]
        intermediates = chain[1:-1]

        # Confidence depends on what sits between the Add and Remove.
        has_alter = any(e.class_name == "AlterField" for e in intermediates)
        runpython_nearby = self._has_runpython_between(add_ev, remove_ev, ctx)
        if runpython_nearby:
            confidence = CONFIDENCE_WITH_RUNPYTHON_NEARBY
        elif has_alter:
            confidence = CONFIDENCE_WITH_ALTERS
        else:
            confidence = CONFIDENCE_CLEAN_PAIR

        migrations = [(e.app, e.migration_name) for e in chain]
        detail_lines = [f"Field `{model}.{field}` lifecycle:"]
        for e in chain:
            detail_lines.append(f"  - {e.class_name} in {e.app}.{e.migration_name}")
        if runpython_nearby:
            detail_lines.append(
                "  ⚠ RunPython ops exist in the gap — verify no external side effects before squashing."
            )

        return Finding(
            detector_name=self.name,
            kind="add_remove_field_loop",
            summary=f"`{model}.{field}` added in {add_ev.migration_name} then removed in {remove_ev.migration_name}",
            confidence=confidence,
            migrations=migrations,
            detail="\n".join(detail_lines),
            metadata={
                "app": app,
                "model": model,
                "field": field,
                "intermediate_op_types": [e.class_name for e in intermediates],
                "had_runpython_in_gap": runpython_nearby,
            },
        )

    def _has_runpython_between(self, add_ev: TimelineEvent, remove_ev: TimelineEvent, ctx: AnalysisContext) -> bool:
        """Look at the same app's RunPython events ordered by migration name —
        are any between add_ev and remove_ev?"""
        for ev in ctx.timeline.runpython_events:
            if ev.app != add_ev.app:
                continue
            if add_ev.migration_name < ev.migration_name < remove_ev.migration_name:
                return True
        return False
