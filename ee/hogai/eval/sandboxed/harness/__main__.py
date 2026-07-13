from __future__ import annotations

import os
import sys
import logging

from .cli import parse_args
from .django_env import setup_django
from .ports import PERSONHOG_ROUTER_PORT
from .providers import SANDBOX_PROVIDER_SETTING, PreflightError

USAGE_ERROR_EXIT_CODE = 2


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    options = parse_args(argv)

    # Select the sandbox class before Django loads settings. products.tasks resolves
    # settings.SANDBOX_PROVIDER once and caches the class in module globals, so the
    # async-phase override_settings runs too late to change it. .env ships
    # SANDBOX_PROVIDER=docker, so without this a modal run would cache DockerSandbox
    # and execute locally. See SANDBOX_PROVIDER_SETTING.
    os.environ["SANDBOX_PROVIDER"] = SANDBOX_PROVIDER_SETTING[options.provider]

    # Point person/group reads at the harness's own personhog router before Django
    # loads settings. PERSONHOG_ADDR is read from env once at django.setup(), and the
    # personhog client is a cached singleton keyed off that setting at its first call.
    # Bootstrap-phase reads (demo seeding, taxonomy inference) run before the
    # async-phase override_settings, so setting it there would be too late — the
    # singleton is already built. A PERSONHOG_ADDR leaked from a sourced dev .env
    # would otherwise silently point eval reads at the dev persons DB.
    os.environ["PERSONHOG_ADDR"] = f"127.0.0.1:{PERSONHOG_ROUTER_PORT}"

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
