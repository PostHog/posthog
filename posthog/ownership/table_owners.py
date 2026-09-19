"""Map every Postgres table Django knows about to the team that owns its model.

The output is embedded in pgcollector so slow queries can be attributed to a team.
Only the app registry is read; no database connection is needed.
"""

import json
import inspect
from pathlib import Path
from typing import Literal

from django.apps import apps

from posthog_owners.resolver import OwnersResolver

from posthog.dataclasses import frozen
from posthog.product_db_config import load_product_db_routes

OUTPUT_PATH = "rust/pgcollector/ownership/table_owners.json"

TableKind = Literal["django", "through", "third_party"]


@frozen
class TableOwner:
    db_table: str
    model: str
    app_label: str
    database: str
    kind: TableKind
    owners: tuple[str, ...]
    slack: str | None
    notifications: str | None
    source: str | None


def table_owners(repo_root: Path) -> list[TableOwner]:
    routes = {r.app_label: r.database for r in load_product_db_routes(repo_root)}
    people = OwnersResolver(repo_root=repo_root, purpose="slack")
    automation = OwnersResolver(repo_root=repo_root, purpose="notifications")
    records: dict[str, TableOwner] = {}
    for model in apps.get_models(include_auto_created=True):
        meta = model._meta
        # An auto-created M2M through table has no source file of its own; the model that
        # declares the relation owns it.
        # django-stubs types auto_created as bool, but Django stores the declaring model there.
        auto_created: object = meta.auto_created
        origin = auto_created if isinstance(auto_created, type) else model
        kind: TableKind = "through" if isinstance(auto_created, type) else "django"
        source = _repo_relative_source(origin, repo_root)
        if source is None:
            kind = "third_party"
        resolution = people.resolve(source) if source else None
        records[meta.db_table] = TableOwner(
            db_table=meta.db_table,
            model=f"{meta.app_label}.{model.__name__}",
            app_label=meta.app_label,
            database=routes.get(meta.app_label, "default"),
            kind=kind,
            owners=tuple(resolution.owners or ()) if resolution else (),
            slack=resolution.slack if resolution else None,
            notifications=automation.resolve(source).slack if source else None,
            source=source,
        )
    return [records[t] for t in sorted(records)]


def _repo_relative_source(model: type, repo_root: Path) -> str | None:
    path = inspect.getsourcefile(model)
    if path is None:
        return None
    resolved = Path(path).resolve()
    # The dev venv can live under the repo root (.flox, .venv), so a relative path alone
    # does not prove the model is ours.
    if "site-packages" in resolved.parts:
        return None
    try:
        return resolved.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return None


def render_json(records: list[TableOwner]) -> str:
    tables = {
        r.db_table: {
            "model": r.model,
            "app_label": r.app_label,
            "database": r.database,
            "kind": r.kind,
            "owners": list(r.owners),
            "slack": r.slack,
            "notifications": r.notifications,
            "source": r.source,
        }
        for r in records
    }
    return json.dumps({"version": 1, "tables": tables}, indent=2, sort_keys=False) + "\n"


def unowned_report(records: list[TableOwner]) -> list[str]:
    return [f"{r.db_table}\t{r.kind}\t{r.source or r.model}" for r in records if not r.owners]
