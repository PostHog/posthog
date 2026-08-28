"""Dump every registered warehouse source's endpoint inventory as JSON, credential-free.

Run from the repo root:

    flox activate -- bash -c "PYTHONPATH=. python \
        .agents/skills/auditing-warehouse-source-coverage/scripts/dump_source_inventory.py > /tmp/inventory.json"

Reports what `get_schemas` actually returns (via `get_documented_tables`, which builds a
placeholder config), so it needs no credentials and makes no vendor API calls. Sources that
raise while listing record the error and are skipped rather than aborting the dump.

Django writes a DEBUG-mode warning to stdout first, so strip everything before the first `{`.
"""

import os
import sys
import json

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import (  # noqa: E402 — must follow django.setup()
    SourceRegistry,
)


def main() -> None:
    out: dict[str, dict] = {}

    for source_type, source in SourceRegistry.get_all_sources().items():
        entry: dict = {"source_type": str(source_type)}

        try:
            config = source.get_source_config
            entry["label"] = getattr(config, "label", None)
            entry["category"] = str(getattr(config, "category", None))
            entry["unreleased"] = bool(getattr(config, "unreleasedSource", False))
            entry["release_status"] = str(getattr(config, "releaseStatus", None))
            entry["feature_flag"] = getattr(config, "featureFlag", None)
        except Exception as e:
            entry["config_error"] = repr(e)

        # SQL and file sources introspect user-defined schemas, so they have no fixed endpoint
        # set and are out of scope for a coverage audit.
        try:
            entry["lists_tables_without_credentials"] = bool(source.lists_tables_without_credentials)
        except Exception:
            entry["lists_tables_without_credentials"] = None

        tables: list[dict] = []
        try:
            tables = source.get_documented_tables()
        except Exception as e:
            entry["tables_error"] = repr(e)
        entry["tables"] = [t.get("name") for t in tables]
        entry["table_count"] = len(tables)

        canonical: dict = {}
        try:
            canonical = source.get_canonical_descriptions()
        except Exception as e:
            entry["canonical_error"] = repr(e)
        entry["canonical_keys"] = sorted(canonical.keys())
        entry["canonical_count"] = len(canonical)
        # docs_url per endpoint is the fastest route to the vendor page for a given table.
        entry["docs_urls"] = sorted(
            {v.get("docs_url") for v in canonical.values() if isinstance(v, dict) and v.get("docs_url")}
        )

        out[str(source_type)] = entry

    json.dump(out, sys.stdout, indent=1, default=str)


if __name__ == "__main__":
    main()
