"""Alive-set computation and op classification."""

from __future__ import annotations

from pathlib import Path

from posthog.management.migration_profiling.dead_code.parser import parse_migration_file
from posthog.management.migration_profiling.dead_code.timeline import build_timeline
from posthog.management.migration_profiling.dead_code.waste_analysis import (
    AVOIDABLE_CATEGORIES,
    WasteCategory,
    classify_op,
    compute_alive_set,
    compute_waste_breakdown,
)


def _write(tmp_path: Path, name: str, body: str) -> None:
    path = tmp_path / "posthog" / "migrations" / f"{name}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def _build_timeline(tmp_path: Path):
    parsed = []
    for mig in sorted(tmp_path.rglob("migrations/*.py")):
        p = parse_migration_file(mig)
        if p is not None:
            parsed.append(p)
    return build_timeline(parsed)


class TestAliveSet:
    def test_field_added_then_removed_is_dead(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "0001_add",
            """
from django.db import migrations, models
class Migration(migrations.Migration):
    operations = [migrations.AddField(model_name='event', name='color', field=models.CharField())]
""",
        )
        _write(
            tmp_path,
            "0002_remove",
            """
from django.db import migrations
class Migration(migrations.Migration):
    operations = [migrations.RemoveField(model_name='event', name='color')]
""",
        )
        alive = compute_alive_set(_build_timeline(tmp_path))
        assert ("posthog", "event", "color") not in alive.fields

    def test_field_only_added_is_alive(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "0001_add",
            """
from django.db import migrations, models
class Migration(migrations.Migration):
    operations = [migrations.AddField(model_name='event', name='color', field=models.CharField())]
""",
        )
        alive = compute_alive_set(_build_timeline(tmp_path))
        assert ("posthog", "event", "color") in alive.fields

    def test_last_alter_tracking(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "0001_add",
            """
from django.db import migrations, models
class Migration(migrations.Migration):
    operations = [migrations.AddField(model_name='event', name='color', field=models.CharField())]
""",
        )
        _write(
            tmp_path,
            "0002_alter_a",
            """
from django.db import migrations, models
class Migration(migrations.Migration):
    operations = [migrations.AlterField(model_name='event', name='color', field=models.TextField())]
""",
        )
        _write(
            tmp_path,
            "0003_alter_b",
            """
from django.db import migrations, models
class Migration(migrations.Migration):
    operations = [migrations.AlterField(model_name='event', name='color', field=models.CharField(max_length=20))]
""",
        )
        alive = compute_alive_set(_build_timeline(tmp_path))
        assert alive.last_alter_per_field[("posthog", "event", "color")] == "0003_alter_b"

    def test_model_created_then_deleted_is_dead(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "0001_create",
            """
from django.db import migrations, models
class Migration(migrations.Migration):
    operations = [migrations.CreateModel(name='Stale', fields=[])]
""",
        )
        _write(
            tmp_path,
            "0002_delete",
            """
from django.db import migrations
class Migration(migrations.Migration):
    operations = [migrations.DeleteModel(name='Stale')]
""",
        )
        alive = compute_alive_set(_build_timeline(tmp_path))
        assert ("posthog", "Stale") not in alive.models


class TestClassifyOp:
    def test_addfield_on_alive_target_is_essential(self) -> None:
        from posthog.management.migration_profiling.dead_code.waste_analysis import AliveSet

        alive = AliveSet(fields={("posthog", "event", "color")})
        op = {
            "operation_type": "AddField",
            "app_label": "posthog",
            "migration_name": "0001_add",
            "metadata": {"model_name": "event", "field_name": "color"},
            "is_state_only": False,
            "duration_ms": 5.0,
        }
        assert classify_op(op, alive, alive.last_alter_per_field) == WasteCategory.ESSENTIAL_CREATE

    def test_addfield_on_dead_target_is_dead(self) -> None:
        from posthog.management.migration_profiling.dead_code.waste_analysis import AliveSet

        alive = AliveSet(fields=set())
        op = {
            "operation_type": "AddField",
            "app_label": "posthog",
            "migration_name": "0001_add",
            "metadata": {"model_name": "event", "field_name": "color"},
            "is_state_only": False,
            "duration_ms": 5.0,
        }
        assert classify_op(op, alive, alive.last_alter_per_field) == WasteCategory.DEAD_TARGET

    def test_alterfield_not_last_is_redundant(self) -> None:
        from posthog.management.migration_profiling.dead_code.waste_analysis import AliveSet

        alive = AliveSet(
            fields={("posthog", "event", "color")},
            last_alter_per_field={("posthog", "event", "color"): "0003_alter_b"},
        )
        op = {
            "operation_type": "AlterField",
            "app_label": "posthog",
            "migration_name": "0002_alter_a",  # not the last alter
            "metadata": {"model_name": "event", "field_name": "color"},
            "is_state_only": False,
            "duration_ms": 5.0,
        }
        assert classify_op(op, alive, alive.last_alter_per_field) == WasteCategory.REDUNDANT_RESHAPE

    def test_alterfield_last_is_essential(self) -> None:
        from posthog.management.migration_profiling.dead_code.waste_analysis import AliveSet

        alive = AliveSet(
            fields={("posthog", "event", "color")},
            last_alter_per_field={("posthog", "event", "color"): "0003_alter_b"},
        )
        op = {
            "operation_type": "AlterField",
            "app_label": "posthog",
            "migration_name": "0003_alter_b",
            "metadata": {"model_name": "event", "field_name": "color"},
            "is_state_only": False,
            "duration_ms": 5.0,
        }
        assert classify_op(op, alive, alive.last_alter_per_field) == WasteCategory.ESSENTIAL_RESHAPE

    def test_runpython_is_backfill(self) -> None:
        from posthog.management.migration_profiling.dead_code.waste_analysis import AliveSet

        alive = AliveSet()
        op = {
            "operation_type": "RunPython",
            "app_label": "posthog",
            "migration_name": "0001",
            "metadata": {},
            "is_state_only": False,
            "duration_ms": 50.0,
        }
        assert classify_op(op, alive, {}) == WasteCategory.BACKFILL

    def test_sdas_is_state_only(self) -> None:
        from posthog.management.migration_profiling.dead_code.waste_analysis import AliveSet

        op = {
            "operation_type": "SeparateDatabaseAndState",
            "app_label": "posthog",
            "migration_name": "0001",
            "metadata": {},
            "is_state_only": True,
            "duration_ms": 0.001,
        }
        assert classify_op(op, AliveSet(), {}) == WasteCategory.STATE_ONLY


class TestComputeBreakdown:
    def test_aggregates_sql_and_state_machine(self) -> None:
        from posthog.management.migration_profiling.dead_code.waste_analysis import AliveSet

        alive = AliveSet(
            fields={("posthog", "event", "color")},
            last_alter_per_field={("posthog", "event", "color"): "0003"},
        )
        profile_ops = [
            # Essential AddField in mig A.
            {
                "operation_type": "AddField",
                "app_label": "posthog",
                "migration_name": "0001",
                "metadata": {"model_name": "event", "field_name": "color"},
                "is_state_only": False,
                "duration_ms": 5.0,
            },
            # Backfill RunPython in mig B (no essential op in B → state cost is avoidable).
            {
                "operation_type": "RunPython",
                "app_label": "posthog",
                "migration_name": "0002",
                "metadata": {},
                "is_state_only": False,
                "duration_ms": 10.0,
            },
            # Essential AlterField (last) in mig C.
            {
                "operation_type": "AlterField",
                "app_label": "posthog",
                "migration_name": "0003",
                "metadata": {"model_name": "event", "field_name": "color"},
                "is_state_only": False,
                "duration_ms": 3.0,
            },
        ]
        summaries = {
            ("posthog", "0001"): 100.0,
            ("posthog", "0002"): 80.0,
            ("posthog", "0003"): 90.0,
        }
        breakdown = compute_waste_breakdown(profile_ops, summaries, alive)

        # SQL split.
        assert breakdown.sql_ms_by_category[WasteCategory.ESSENTIAL_CREATE] == 5.0
        assert breakdown.sql_ms_by_category[WasteCategory.ESSENTIAL_RESHAPE] == 3.0
        assert breakdown.sql_ms_by_category[WasteCategory.BACKFILL] == 10.0
        # Backfill is in AVOIDABLE_CATEGORIES.
        assert WasteCategory.BACKFILL in AVOIDABLE_CATEGORIES
        # State machine: mig 0002 has only backfill (no essential) → its 70ms state cost is avoidable.
        # mig 0001 has essential (95ms state), mig 0003 has essential (87ms state).
        assert breakdown.state_machine_avoidable_ms == 70.0
        assert breakdown.state_machine_essential_ms == 95.0 + 87.0
        # New semantics: total_avoidable = avoidable SQL + ALL state-machine beyond
        # a one-migration floor (5000ms). With only 252ms total state-machine here
        # (under the floor), state machine contributes 0 to amortizable. So
        # total_avoidable = 10ms (backfill SQL) only.
        assert breakdown.total_avoidable_ms == 10.0
        # Floor = essential SQL (8ms) + min(252ms, 5000ms) = 260ms.
        assert breakdown.theoretical_floor_ms == 8.0 + 252.0
