from __future__ import annotations

import sys
import logging

from .cli import parse_args
from .django_env import setup_django
from .providers import PreflightError

USAGE_ERROR_EXIT_CODE = 2


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    options = parse_args(argv)

    setup_django()

    # Deferred so Django is configured first: everything below reaches settings,
    # the ORM, or the products.tasks facade at import time.
    from .discovery import SuiteDiscoveryError  # noqa: PLC0415 — must import after django.setup()
    from .lifecycle import SandboxedEvalHarness  # noqa: PLC0415 — must import after django.setup()

    try:
        return SandboxedEvalHarness(options).run()
    except (PreflightError, SuiteDiscoveryError) as e:
        # A missing prerequisite or a typo'd selector is user error, not a harness
        # bug: say what's wrong without a traceback.
        print(f"error: {e}", file=sys.stderr)  # noqa: T201
        return USAGE_ERROR_EXIT_CODE


if __name__ == "__main__":
    sys.exit(main())
