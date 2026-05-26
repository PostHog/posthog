"""Detector A and Detector F against hand-crafted migration trees."""

from __future__ import annotations

from pathlib import Path

from posthog.management.migration_profiling.dead_code.detector_base import AnalysisContext
from posthog.management.migration_profiling.dead_code.detectors.add_remove_field import AddRemoveFieldDetector
from posthog.management.migration_profiling.dead_code.detectors.empty_runpython import EmptyRunPythonDetector
from posthog.management.migration_profiling.dead_code.parser import parse_migration_file
from posthog.management.migration_profiling.dead_code.timeline import build_timeline


def _write_migration(tmp_path: Path, app: str, name: str, body: str) -> None:
    path = tmp_path / app / "migrations" / f"{name}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def _build_ctx(tmp_path: Path) -> AnalysisContext:
    parsed = []
    for mig_file in sorted(tmp_path.rglob("migrations/*.py")):
        p = parse_migration_file(mig_file)
        if p is not None:
            parsed.append(p)
    timeline = build_timeline(parsed)
    return AnalysisContext(
        timeline=timeline,
        migrations=parsed,
        migrations_by_app_name={(m.app, m.name): m for m in parsed},
        profile_ops=[],
    )


class TestAddRemoveFieldDetector:
    def test_clean_add_then_remove_is_high_confidence(self, tmp_path: Path) -> None:
        _write_migration(
            tmp_path,
            "posthog",
            "0001_initial",
            """
from django.db import migrations, models

class Migration(migrations.Migration):
    operations = [
        migrations.AddField(model_name='event', name='color', field=models.CharField()),
    ]
""",
        )
        _write_migration(
            tmp_path,
            "posthog",
            "0002_remove_color",
            """
from django.db import migrations

class Migration(migrations.Migration):
    operations = [
        migrations.RemoveField(model_name='event', name='color'),
    ]
""",
        )
        ctx = _build_ctx(tmp_path)
        findings = list(AddRemoveFieldDetector().run(ctx))
        assert len(findings) == 1
        f = findings[0]
        assert f.confidence == 0.95
        assert f.metadata["model"] == "event"
        assert f.metadata["field"] == "color"
        assert ("posthog", "0001_initial") in f.migrations
        assert ("posthog", "0002_remove_color") in f.migrations

    def test_add_alter_remove_keeps_high_confidence(self, tmp_path: Path) -> None:
        _write_migration(
            tmp_path,
            "posthog",
            "0001_add",
            """
from django.db import migrations, models
class Migration(migrations.Migration):
    operations = [migrations.AddField(model_name='event', name='color', field=models.CharField())]
""",
        )
        _write_migration(
            tmp_path,
            "posthog",
            "0002_alter",
            """
from django.db import migrations, models
class Migration(migrations.Migration):
    operations = [migrations.AlterField(model_name='event', name='color', field=models.TextField())]
""",
        )
        _write_migration(
            tmp_path,
            "posthog",
            "0003_remove",
            """
from django.db import migrations
class Migration(migrations.Migration):
    operations = [migrations.RemoveField(model_name='event', name='color')]
""",
        )
        ctx = _build_ctx(tmp_path)
        findings = list(AddRemoveFieldDetector().run(ctx))
        assert len(findings) == 1
        assert findings[0].confidence == 0.90
        assert findings[0].metadata["intermediate_op_types"] == ["AlterField"]

    def test_runpython_between_lowers_confidence(self, tmp_path: Path) -> None:
        _write_migration(
            tmp_path,
            "posthog",
            "0001_add",
            """
from django.db import migrations, models
class Migration(migrations.Migration):
    operations = [migrations.AddField(model_name='event', name='color', field=models.CharField())]
""",
        )
        _write_migration(
            tmp_path,
            "posthog",
            "0002_backfill",
            """
from django.db import migrations

def fill(apps, schema_editor):
    Event = apps.get_model('posthog', 'Event')
    Event.objects.update(color='red')

class Migration(migrations.Migration):
    operations = [migrations.RunPython(fill)]
""",
        )
        _write_migration(
            tmp_path,
            "posthog",
            "0003_remove",
            """
from django.db import migrations
class Migration(migrations.Migration):
    operations = [migrations.RemoveField(model_name='event', name='color')]
""",
        )
        ctx = _build_ctx(tmp_path)
        findings = list(AddRemoveFieldDetector().run(ctx))
        assert len(findings) == 1
        assert findings[0].confidence == 0.60
        assert findings[0].metadata["had_runpython_in_gap"] is True

    def test_field_readded_does_not_match_first_remove(self, tmp_path: Path) -> None:
        # Add, then add again — no remove → no finding. Sanity check.
        _write_migration(
            tmp_path,
            "posthog",
            "0001_add",
            """
from django.db import migrations, models
class Migration(migrations.Migration):
    operations = [migrations.AddField(model_name='event', name='color', field=models.CharField())]
""",
        )
        _write_migration(
            tmp_path,
            "posthog",
            "0002_add_again",
            """
from django.db import migrations, models
class Migration(migrations.Migration):
    operations = [migrations.AddField(model_name='event', name='color', field=models.TextField())]
""",
        )
        ctx = _build_ctx(tmp_path)
        findings = list(AddRemoveFieldDetector().run(ctx))
        assert findings == []

    def test_no_finding_for_only_an_add(self, tmp_path: Path) -> None:
        _write_migration(
            tmp_path,
            "posthog",
            "0001_add",
            """
from django.db import migrations, models
class Migration(migrations.Migration):
    operations = [migrations.AddField(model_name='event', name='color', field=models.CharField())]
""",
        )
        ctx = _build_ctx(tmp_path)
        findings = list(AddRemoveFieldDetector().run(ctx))
        assert findings == []


class TestEmptyRunPythonDetector:
    def test_explicit_noop_sentinel(self, tmp_path: Path) -> None:
        _write_migration(
            tmp_path,
            "posthog",
            "0001_noop",
            """
from django.db import migrations
class Migration(migrations.Migration):
    operations = [migrations.RunPython(migrations.RunPython.noop)]
""",
        )
        ctx = _build_ctx(tmp_path)
        findings = list(EmptyRunPythonDetector().run(ctx))
        assert len(findings) == 1
        assert findings[0].metadata["detection_kind"] == "explicit_noop"
        assert findings[0].confidence == 1.0

    def test_pass_only_body(self, tmp_path: Path) -> None:
        _write_migration(
            tmp_path,
            "posthog",
            "0001_pass",
            """
from django.db import migrations

def empty(apps, schema_editor):
    pass

class Migration(migrations.Migration):
    operations = [migrations.RunPython(empty)]
""",
        )
        ctx = _build_ctx(tmp_path)
        findings = list(EmptyRunPythonDetector().run(ctx))
        assert len(findings) == 1
        assert findings[0].metadata["detection_kind"] == "empty_body"
        assert findings[0].metadata["callable"] == "empty"

    def test_docstring_only_body_still_empty(self, tmp_path: Path) -> None:
        _write_migration(
            tmp_path,
            "posthog",
            "0001_doc",
            """
from django.db import migrations

def doc_only(apps, schema_editor):
    '''No longer needed.'''
    pass

class Migration(migrations.Migration):
    operations = [migrations.RunPython(doc_only)]
""",
        )
        ctx = _build_ctx(tmp_path)
        findings = list(EmptyRunPythonDetector().run(ctx))
        assert len(findings) == 1

    def test_return_none_body(self, tmp_path: Path) -> None:
        _write_migration(
            tmp_path,
            "posthog",
            "0001_ret",
            """
from django.db import migrations

def returns(apps, schema_editor):
    return None

class Migration(migrations.Migration):
    operations = [migrations.RunPython(returns)]
""",
        )
        ctx = _build_ctx(tmp_path)
        findings = list(EmptyRunPythonDetector().run(ctx))
        assert len(findings) == 1

    def test_active_body_no_finding(self, tmp_path: Path) -> None:
        _write_migration(
            tmp_path,
            "posthog",
            "0001_active",
            """
from django.db import migrations

def real(apps, schema_editor):
    Event = apps.get_model('posthog', 'Event')
    Event.objects.update(color='red')

class Migration(migrations.Migration):
    operations = [migrations.RunPython(real)]
""",
        )
        ctx = _build_ctx(tmp_path)
        findings = list(EmptyRunPythonDetector().run(ctx))
        assert findings == []
