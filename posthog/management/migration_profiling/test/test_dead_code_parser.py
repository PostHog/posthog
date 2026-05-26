"""AST parser handles real-shape migration files."""

from __future__ import annotations

from pathlib import Path

from posthog.management.migration_profiling.dead_code.parser import parse_migration_file


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / "posthog" / "migrations" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


class TestParser:
    def test_parses_addfield_with_kwargs(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "0001_initial.py",
            """
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = []
    operations = [
        migrations.AddField(
            model_name='event',
            name='color',
            field=models.CharField(max_length=10),
        ),
    ]
""",
        )
        parsed = parse_migration_file(path)
        assert parsed is not None
        assert parsed.app == "posthog"
        assert parsed.name == "0001_initial"
        assert len(parsed.operations) == 1
        op = parsed.operations[0]
        assert op.class_name == "AddField"
        assert op.kwargs["model_name"] == "event"
        assert op.kwargs["name"] == "color"

    def test_parses_positional_addfield(self, tmp_path: Path) -> None:
        # Older PostHog migrations sometimes pass positional args.
        path = _write(
            tmp_path,
            "0002_positional.py",
            """
from django.db import migrations, models

class Migration(migrations.Migration):
    operations = [
        migrations.AddField('event', 'color', models.CharField()),
    ]
""",
        )
        parsed = parse_migration_file(path)
        assert parsed is not None
        op = parsed.operations[0]
        assert op.class_name == "AddField"
        assert op.kwargs["model_name"] == "event"
        assert op.kwargs["name"] == "color"

    def test_parses_runpython_with_callable(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "0003_runpython.py",
            """
from django.db import migrations

def my_forward(apps, schema_editor):
    Foo = apps.get_model('posthog', 'Foo')
    Foo.objects.update(x=1)

class Migration(migrations.Migration):
    operations = [
        migrations.RunPython(my_forward),
    ]
""",
        )
        parsed = parse_migration_file(path)
        assert parsed is not None
        op = parsed.operations[0]
        assert op.class_name == "RunPython"
        assert op.runpython_callable_name == "my_forward"
        assert op.runpython_is_explicit_noop is False
        assert op.runpython_callable_body_source is not None
        assert "Foo.objects.update" in op.runpython_callable_body_source

    def test_parses_runpython_noop_sentinel(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "0004_noop.py",
            """
from django.db import migrations

class Migration(migrations.Migration):
    operations = [
        migrations.RunPython(migrations.RunPython.noop),
    ]
""",
        )
        parsed = parse_migration_file(path)
        assert parsed is not None
        op = parsed.operations[0]
        assert op.class_name == "RunPython"
        assert op.runpython_is_explicit_noop is True

    def test_handles_syntax_error_gracefully(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "0005_broken.py", "this is not python (((")
        parsed = parse_migration_file(path)
        assert parsed is None

    def test_app_inference_product_layout(self, tmp_path: Path) -> None:
        path = tmp_path / "products" / "conversations" / "backend" / "migrations" / "0001_initial.py"
        path.parent.mkdir(parents=True)
        path.write_text(
            "from django.db import migrations\nclass Migration(migrations.Migration):\n    operations = []\n"
        )
        parsed = parse_migration_file(path)
        assert parsed is not None
        assert parsed.app == "conversations"
