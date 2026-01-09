"""PostHog-specific hogli commands.

This package contains custom Click commands for the PostHog monorepo.
The hogli framework itself lives in tools/hogli/.
"""

# Import commands module to register @cli.command() decorated functions
from . import commands  # noqa: F401
