"""Management command that generates the OpenAPI schema and fails on errors.

Wraps drf-spectacular's ``spectacular`` command but only fails on actionable
issues (errors, operationId collisions, component name problems) — not on
cosmetic enum naming warnings that drf-spectacular auto-resolves.
"""

from drf_spectacular.drainage import GENERATOR_STATS
from drf_spectacular.management.commands.spectacular import (
    Command as SpectacularCommand,
    SchemaGenerationError,
)

# Enum naming warnings are cosmetic — drf-spectacular auto-resolves them with
# hash suffixes and the generated schema is valid.  We skip these so the CI
# gate only fires on real problems.
_IGNORED_WARNING_PATTERNS = (
    "ENUM_NAME_OVERRIDES",
    "encountered multiple names for the same choice set",
)


class Command(SpectacularCommand):
    help = "Generate OpenAPI schema and fail on errors or serious warnings (CI gate)."

    def handle(self, *args, **options):
        options["fail_on_warn"] = False
        super().handle(*args, **options)

        errors = dict(GENERATOR_STATS._error_cache)
        warnings = {
            msg: count
            for msg, count in GENERATOR_STATS._warn_cache.items()
            if not any(pattern in msg for pattern in _IGNORED_WARNING_PATTERNS)
        }

        if errors or warnings:
            parts = []
            if errors:
                parts.append(f"{len(errors)} error(s)")
            if warnings:
                parts.append(f"{len(warnings)} warning(s)")
            raise SchemaGenerationError(
                f"OpenAPI schema has {', '.join(parts)}. "
                "Fix ViewSet/serializer annotations — see output above for details."
            )
