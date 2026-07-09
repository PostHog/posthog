"""Global dashboard template seeds for local dev (same idea as ``demo/legacy/*.json`` next to generators).

JSON payloads live in this directory beside this package (like ``demo_people.json`` beside ``web_data_generator.py``).
Loaded in lexicographic order; use ``01_…``, ``02_…`` filename prefixes to control order.

Used by ``generate_demo_data`` and ``ensure_migration_defaults``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SEED_JSON_DIR = Path(__file__).resolve().parent


def load_dashboard_template_seeds() -> list[dict[str, Any]]:
    """Every ``*.json`` in this directory (sorted by filename)."""
    out: list[dict[str, Any]] = []
    for path in sorted(_SEED_JSON_DIR.glob("*.json")):
        out.append(json.loads(path.read_text()))
    return out


def seed_dev_dashboard_templates() -> list[str]:
    """Insert global dashboard templates if missing. Returns names of templates created."""
    from products.dashboards.backend.models.dashboard_templates import DashboardTemplate

    created: list[str] = []
    for payload in load_dashboard_template_seeds():
        name = payload.get("template_name")
        if not name:
            raise ValueError(f"Dashboard template seed missing or has null 'template_name': {payload}")
        exists = DashboardTemplate.objects.filter(team_id__isnull=True, template_name=name).exists()
        if exists:
            continue
        DashboardTemplate.objects.create(
            team_id=None,
            template_name=name,
            dashboard_description=payload.get("dashboard_description"),
            dashboard_filters=payload.get("dashboard_filters"),
            tiles=payload.get("tiles"),
            variables=payload.get("variables"),
            tags=payload.get("tags") or [],
            image_url=payload.get("image_url"),
            scope=payload.get("scope") or DashboardTemplate.Scope.GLOBAL,
            availability_contexts=payload.get("availability_contexts"),
        )
        created.append(name)
    return created
