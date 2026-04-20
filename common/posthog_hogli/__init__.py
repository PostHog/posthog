"""PostHog-specific hogli commands.

This package contains custom Click commands for the PostHog monorepo.
The hogli framework itself lives in tools/hogli/.
"""

import sys

# Import commands to register @cli.command() decorators. Skip if a sibling import path
# already loaded them — pytest imports this package as both `common.posthog_hogli` and
# `posthog_hogli` because `common/` is a package and is also on sys.path, so running the
# registrations twice attaches two callbacks with different __module__ values and breaks
# mock.patch targets.
if not any(k.endswith(".posthog_hogli.commands") or k == "posthog_hogli.commands" for k in sys.modules):
    from . import commands  # noqa: F401
