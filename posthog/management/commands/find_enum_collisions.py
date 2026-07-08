"""Find drf-spectacular enum naming collisions and suggest ENUM_NAME_OVERRIDES entries.

Replicates the collision detection logic from drf_spectacular.hooks.postprocess_schema_enums
but prints actionable output instead of opaque warnings.

Run this when `hogli build:openapi-schema` fails with messages like
"enum naming encountered a non-optimally resolvable collision" / "Format5eaEnum" — it
prints a suggested ENUM_NAME_OVERRIDES entry for posthog/settings/web.py. The suggestion
is pastable as-is for type-hint enum collisions and for ChoiceField collisions whose
choices are plain inline lists (labels == values); only ChoiceField collisions with
custom labels (e.g. a `TextChoices` class where labels differ from values) need the
model class path filled in.

See also:
    posthog/settings/web.py — ENUM_NAME_OVERRIDES (where the fix goes)
    /improving-drf-endpoints — skill with the full DRF/OpenAPI guide

Usage:
    python manage.py find_enum_collisions
"""

from __future__ import annotations

import os
import json

from django.core.management.base import BaseCommand

from drf_spectacular.drainage import GENERATOR_STATS
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.plumbing import load_enum_name_overrides
from drf_spectacular.settings import spectacular_settings

# Collision logic lives in posthog.openapi.enum_collisions so CI
# (test_widget_openapi_enums.py) and this command share one implementation.
from posthog.openapi.enum_collisions import collect_enum_hashes, find_unresolved_enum_collisions


class Command(BaseCommand):
    help = "Find drf-spectacular enum collisions and suggest ENUM_NAME_OVERRIDES entries"

    def handle(self, *args: object, **options: object) -> None:
        os.environ.setdefault("OPENAPI_INCLUDE_INTERNAL", "1")
        os.environ.setdefault("OPENAPI_MOCK_INTERNAL_API_SECRET", "1")

        GENERATOR_STATS.enable_trace_lineno()

        self.stderr.write("Generating schema (this takes ~30s)...")
        gen = SchemaGenerator()

        orig_hooks = list(spectacular_settings.POSTPROCESSING_HOOKS)
        spectacular_settings.POSTPROCESSING_HOOKS = []  # type: ignore[attr-defined]
        schema = gen.get_schema(request=None, public=True)
        spectacular_settings.POSTPROCESSING_HOOKS = orig_hooks  # type: ignore[attr-defined]

        schemas = schema.get("components", {}).get("schemas", {})
        collisions = find_unresolved_enum_collisions(schemas)

        if not collisions:
            self.stdout.write(self.style.SUCCESS("No enum collisions found."))
            return

        self.stdout.write(f"\nFound {len(collisions)} enum collision(s):\n")

        for c in collisions:
            self.stdout.write(f"  Field: {c['field']}")
            self.stdout.write(f"  Auto-resolved as: {c['auto_name']}")
            self.stdout.write(f"  Hash: {c['hash']}")
            self.stdout.write(f"  Values: {c['values']}")
            path = "x-spec-enum-id (ChoiceField)" if c["has_spec_id"] else "inline (type-hint)"
            self.stdout.write(f"  Hash path: {path}")
            self.stdout.write(f"  Used in {len(c['components'])} components:")
            for comp, field in c["components"]:
                self.stdout.write(f"    - {comp}.{field}")

            self.stdout.write("")
            self.stdout.write("  Override entry to add to ENUM_NAME_OVERRIDES in web.py")
            self.stdout.write("  (key defaults to the current auto-resolved name; rename for a nicer schema type):")
            if c["has_spec_id"] and not c["inline_override_matches"]:
                self.stdout.write(f'    "{c["auto_name"]}": "your.models.module.Model.ChoicesClass",')
                self.stdout.write(
                    "    # ChoiceField with custom labels (labels != values) — override must be a model class path"
                )
            else:
                vals = c["values"]
                if all(isinstance(v, int) for v in vals):
                    formatted = [(v, v) for v in vals]
                    self.stdout.write(f'    "{c["auto_name"]}": {formatted},')
                else:
                    self.stdout.write(f'    "{c["auto_name"]}": {json.dumps(vals)},')
                if c["has_spec_id"]:
                    self.stdout.write(
                        "    # ChoiceField with inline choices (labels == values) — paste as-is to silence the warning"
                    )
                else:
                    self.stdout.write("    # Type-hint path — paste as-is to silence the warning")
            self.stdout.write("\n  ---\n")

        overrides = load_enum_name_overrides()
        all_hashes = collect_enum_hashes(schemas)
        stale = [(name, h) for h, name in overrides.items() if h not in all_hashes]
        if stale:
            self.stdout.write("Stale overrides (hash not found in schema, may be removable):")
            for name, h in sorted(stale):
                self.stdout.write(f"  {name} (hash: {h})")
            self.stdout.write("")
