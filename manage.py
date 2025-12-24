#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys
from pathlib import Path

# Add common/ to path so hogli module is importable (used by custom migrate command)
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
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
