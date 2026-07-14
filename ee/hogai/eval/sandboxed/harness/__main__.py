from __future__ import annotations

import os
import sys
import logging

from .cli import HarnessOptions, parse_args
from .django_env import setup_django
from .env_preflight import load_env_file
from .ports import PERSONHOG_ROUTER_PORT
from .providers import SANDBOX_PROVIDER_SETTING, PreflightError
from .transcript import RunTranscript

USAGE_ERROR_EXIT_CODE = 2


def _run(options: HarnessOptions) -> int:
    # Load the repo-root .env before Django reads the environment, so the harness
    # works without a manual `set -a; source .env`. Shell values win, and the
    # explicit overrides below still trump anything an env file provided.
    load_env_file()

    # Select the sandbox class before Django loads settings. products.tasks resolves
    # settings.SANDBOX_PROVIDER once and caches the class in module globals, so the
    # async-phase override_settings runs too late to change it. .env ships
    # SANDBOX_PROVIDER=docker, so without this a modal run would cache DockerSandbox
    # and execute locally. See SANDBOX_PROVIDER_SETTING. Set unconditionally — on a
    # run without sandboxed suites it only selects a class nothing instantiates.
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


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        force=True,
    )


def main(argv: list[str] | None = None) -> int:
    options = parse_args(argv)
    if options.list_only:
        _configure_logging()
        return _run(options)

    transcript = RunTranscript.create()
    exit_code = 1
    try:
        with transcript.capture():
            _configure_logging()
            try:
                exit_code = _run(options)
            except KeyboardInterrupt:
                logging.getLogger(__name__).warning("Interrupted")
                exit_code = 130
            except Exception:
                logging.getLogger(__name__).exception("Sandboxed eval harness failed")
                exit_code = 1
            finally:
                logging.shutdown()
    finally:
        transcript.finish()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
