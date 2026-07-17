#!/usr/bin/env python3
"""Preflight dashboard widget OpenAPI codegen from the backend registry.

Same pattern as ``bin/build-mcp-oauth-scopes.py``: a ``bin/*`` codegen script
invoked from ``hogli build:*``, reading backend SSOT and writing frontend JSON.

Checks every ``WIDGET_SPECS`` type has an ``ENUM_NAME_OVERRIDES`` entry (Orval /
``build:openapi-schema`` fails otherwise) and emits frontend SSOT JSON for date
presets and modal form field picks. Step 2 of ``hogli build:widget-types`` runs
``generate-widget-config-zod.mjs`` (Orval ``generateReusableSchemas`` on the
catalog OpenAPI slice).

Run via hogli: `hogli build:widget-types` (also runs as part of `build:openapi`).
"""
# ruff: noqa: T201

from __future__ import annotations

import os
import sys
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATED_DIR = REPO_ROOT / "products" / "dashboards" / "frontend" / "generated"
DATE_FROM_OPTIONS_JSON = GENERATED_DIR / "widget-date-from-options.json"
FORM_FIELDS_JSON = GENERATED_DIR / "widget-form-fields.json"


def _friendly_config_schema_export(config_model_name: str) -> str:
    type_name = config_model_name
    if type_name.endswith("ListWidgetConfig"):
        type_name = type_name.replace("ListWidgetConfig", "WidgetConfig")
    return type_name[0].lower() + type_name[1:] + "Schema"


def _friendly_config_type_export(config_model_name: str) -> str:
    type_name = config_model_name
    if type_name.endswith("ListWidgetConfig"):
        type_name = type_name.replace("ListWidgetConfig", "WidgetConfig")
    return type_name


def main() -> int:
    # Django imports stay local: django.setup() must run before registry/models load.
    sys.path.insert(0, str(REPO_ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    import django  # noqa: PLC0415

    django.setup()

    from django.conf import settings  # noqa: PLC0415

    from products.dashboards.backend.constants import (  # noqa: PLC0415
        WIDGET_DATE_FROM_LABELS,
        WIDGET_DATE_FROM_VALUES_ORDERED,
    )
    from products.dashboards.backend.widget_specs.registry import WIDGET_SPECS  # noqa: PLC0415

    enum_overrides = settings.SPECTACULAR_SETTINGS.get("ENUM_NAME_OVERRIDES", {})
    override_values = [value for value in enum_overrides.values() if isinstance(value, list)]
    missing_overrides = [
        widget_type for widget_type, _spec in sorted(WIDGET_SPECS.items()) if [widget_type] not in override_values
    ]
    if missing_overrides:
        print(
            "Missing ENUM_NAME_OVERRIDES entries for widget_type(s): "
            + ", ".join(missing_overrides)
            + ". See posthog/settings/web.py and python manage.py find_enum_collisions.",
            file=sys.stderr,
        )
        return 1

    if not WIDGET_SPECS:
        print("No widget specs found in WIDGET_SPECS", file=sys.stderr)
        return 1

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    date_from_options = [
        {"value": value, "label": WIDGET_DATE_FROM_LABELS[value]}
        for value in WIDGET_DATE_FROM_VALUES_ORDERED
        if value in WIDGET_DATE_FROM_LABELS
    ]
    if len(date_from_options) != len(WIDGET_DATE_FROM_VALUES_ORDERED):
        print("WIDGET_DATE_FROM_LABELS is missing entries for WIDGET_DATE_FROM_VALUES_ORDERED", file=sys.stderr)
        return 1

    DATE_FROM_OPTIONS_JSON.write_text(json.dumps({"options": date_from_options}, indent=2) + "\n", encoding="utf-8")
    print(
        f"Wrote {DATE_FROM_OPTIONS_JSON.relative_to(REPO_ROOT)} ({len(date_from_options)} date presets)",
    )

    form_fields_manifest: dict[str, dict[str, object]] = {}
    for widget_type, spec in sorted(WIDGET_SPECS.items()):
        missing_form_fields = set(spec.form_fields) - set(spec.config_model.model_fields)
        if missing_form_fields:
            print(
                f"{widget_type}: form_fields not on config model: {sorted(missing_form_fields)}",
                file=sys.stderr,
            )
            return 1

        config_model_name = spec.config_model.__name__
        config_schema_export = _friendly_config_schema_export(config_model_name)
        form_fields_manifest[widget_type] = {
            "configSchemaExport": config_schema_export,
            "configTypeExport": _friendly_config_type_export(config_model_name),
            "formSchemaExport": config_schema_export.replace("ConfigSchema", "FormSchema"),
            "formFields": list(spec.form_fields),
        }

    FORM_FIELDS_JSON.write_text(json.dumps({"widgets": form_fields_manifest}, indent=2) + "\n", encoding="utf-8")
    print(
        f"Wrote {FORM_FIELDS_JSON.relative_to(REPO_ROOT)} ({len(form_fields_manifest)} widget form manifests)",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
