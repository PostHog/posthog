#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import gc
import os
import sys
from pathlib import Path

# Add common/ to path so migration_utils module is importable (used by custom migrate command)
_common_path = str(Path(__file__).parent / "common")
if _common_path not in sys.path:
    sys.path.insert(0, _common_path)


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    # Boot allocations are almost all permanent (modules, classes, registries), so cyclic GC
    # during django.setup() only adds pauses (~300ms across ~470 collections). Disable it for
    # the boot, then freeze the survivors so later full collections skip them too. Skipped when
    # --settings/--pythonpath override the settings module, since those only take effect inside
    # execute_from_command_line. See docs/internal/django-startup-time.md.
    if not any(arg.startswith(("--settings", "--pythonpath")) for arg in sys.argv):
        gc.disable()
        try:
            import django

            django.setup()
        finally:
            gc.freeze()
            gc.enable()

    # Default query tags so management commands don't trip the DEBUG-only UntaggedQueryError
    # in sync_execute. HTTP requests (runserver's CHQueries middleware) and Celery tasks reset
    # tags at their own boundaries, so this only effectively applies to direct CLI commands.
    from posthog.clickhouse.query_tagging import Feature, Product, tags_context

    with tags_context(product=Product.INTERNAL, feature=Feature.MANAGEMENT_COMMAND):
        execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
