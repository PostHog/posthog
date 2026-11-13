"""Global dashboard template seeds for local dev (same idea as ``demo/legacy/*.json`` next to generators).

JSON payloads live in this directory beside this package (like ``demo_people.json`` beside ``web_data_generator.py``).
Loaded in lexicographic order; use ``01_…``, ``02_…`` filename prefixes to control order.

Used by ``generate_demo_data`` and ``ensure_migration_defaults``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from products.dashboards.backend.facade import api as dashboards_api
from products.dashboards.backend.facade.contracts import DashboardTemplateDefinition
from products.dashboards.backend.facade.enums import DashboardTemplateScope

_SEED_JSON_DIR = Path(__file__).resolve().parent


def load_dashboard_template_seeds() -> list[dict[str, Any]]:
    """Every ``*.json`` in this directory (sorted by filename)."""
    out: list[dict[str, Any]] = []
    for path in sorted(_SEED_JSON_DIR.glob("*.json")):
        out.append(json.loads(path.read_text()))
    return out


def seed_dev_dashboard_templates() -> list[str]:
    """Insert global dashboard templates if missing. Returns names of templates created."""
    created: list[str] = []
    for payload in load_dashboard_template_seeds():
        name = payload.get("template_name")
        if not name:
            raise ValueError(f"Dashboard template seed missing or has null 'template_name': {payload}")
        template = DashboardTemplateDefinition(
            template_name=name,
            dashboard_description=payload.get("dashboard_description"),
            dashboard_filters=payload.get("dashboard_filters"),
            tiles=payload.get("tiles") or [],
            variables=payload.get("variables"),
            tags=payload.get("tags") or [],
            image_url=payload.get("image_url"),
            scope=DashboardTemplateScope(payload.get("scope") or DashboardTemplateScope.GLOBAL),
            availability_contexts=payload.get("availability_contexts"),
        )
        if dashboards_api.create_global_template_if_missing(template):
            created.append(name)
    return created
