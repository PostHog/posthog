from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

VALID_POLICY_ACTIONS = {"keep", "noop", "noop_if_empty"}
_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$")


@dataclass(frozen=True)
class BootstrapPolicyResolution:
    action: str
    reason: str | None
    fingerprint: str | None
    tables: tuple[str, ...] | None


class BootstrapPolicy:
    def __init__(self, entries: dict[tuple[str, str, int, str | None], dict[str, Any]] | None = None) -> None:
        self._entries = entries or {}

    @classmethod
    def from_path(cls, path: Path | None) -> BootstrapPolicy:
        if path is None or not path.exists():
            return cls()
        raw_data = yaml.safe_load(path.read_text())
        return cls.from_data(raw_data, source=str(path))

    @classmethod
    def from_data(cls, raw_data: Any, source: str = "<inline>") -> BootstrapPolicy:
        if raw_data is None:
            return cls()
        if isinstance(raw_data, list):
            raw_entries = raw_data
        elif isinstance(raw_data, dict):
            raw_entries = raw_data.get("entries", [])
        else:
            raise ValueError(f"Invalid bootstrap policy format in {source}: expected mapping or list.")

        if not isinstance(raw_entries, list):
            raise ValueError(f"Invalid bootstrap policy format in {source}: 'entries' must be a list.")

        parsed_entries: dict[tuple[str, str, int, str | None], dict[str, Any]] = {}
        for idx, raw_entry in enumerate(raw_entries, start=1):
            if not isinstance(raw_entry, dict):
                raise ValueError(f"Invalid policy entry #{idx} in {source}: expected mapping.")

            app_label = str(raw_entry.get("app", "")).strip()
            migration = str(raw_entry.get("migration", "")).strip()
            operation_index = raw_entry.get("operation_index")
            nested_path = raw_entry.get("nested_path")
            action = raw_entry.get("action")
            fingerprint = raw_entry.get("fingerprint")
            reason = raw_entry.get("reason")
            tables = raw_entry.get("tables")

            if not app_label or not migration:
                raise ValueError(f"Invalid policy entry #{idx} in {source}: 'app' and 'migration' are required.")
            if operation_index is None:
                raise ValueError(f"Invalid policy entry #{idx} in {source}: 'operation_index' is required.")
            try:
                operation_index_int = int(operation_index)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid policy entry #{idx} in {source}: 'operation_index' must be an integer.")
            if operation_index_int < 1:
                raise ValueError(f"Invalid policy entry #{idx} in {source}: 'operation_index' must be >= 1.")

            nested_path_normalized = None if nested_path in (None, "") else str(nested_path)
            action_normalized = None if action in (None, "") else str(action).strip()
            tables_normalized = cls._normalize_tables(tables=tables, source=source, entry_index=idx)
            if action_normalized is not None and action_normalized not in VALID_POLICY_ACTIONS:
                raise ValueError(
                    f"Invalid policy entry #{idx} in {source}: action '{action_normalized}' is not supported."
                )
            if action_normalized == "noop_if_empty" and not tables_normalized:
                raise ValueError(
                    f"Invalid policy entry #{idx} in {source}: action 'noop_if_empty' requires non-empty 'tables'."
                )
            if action_normalized in {"keep", "noop"} and tables_normalized:
                raise ValueError(
                    f"Invalid policy entry #{idx} in {source}: 'tables' is only valid for action 'noop_if_empty'."
                )

            key = (app_label, migration, operation_index_int, nested_path_normalized)
            if key in parsed_entries:
                raise ValueError(
                    f"Duplicate bootstrap policy entry in {source}: "
                    f"{app_label}.{migration} op#{operation_index_int} nested_path={nested_path_normalized!r}."
                )

            parsed_entries[key] = {
                "app": app_label,
                "migration": migration,
                "operation_index": operation_index_int,
                "nested_path": nested_path_normalized,
                "action": action_normalized,
                "fingerprint": None if fingerprint in (None, "") else str(fingerprint),
                "reason": None if reason in (None, "") else str(reason),
                "tables": tables_normalized,
            }

        return cls(parsed_entries)

    def resolve(
        self,
        app_label: str,
        migration: str,
        operation_index: int,
        nested_path: str | None,
        fingerprint: str,
    ) -> BootstrapPolicyResolution | None:
        key = (app_label, migration, operation_index, nested_path)
        entry = self._entries.get(key)
        if entry is None:
            return None

        expected_fingerprint = entry.get("fingerprint")
        if expected_fingerprint and expected_fingerprint != fingerprint:
            raise ValueError(
                "Bootstrap policy fingerprint mismatch for "
                f"{app_label}.{migration} op#{operation_index} nested_path={nested_path!r}: "
                f"expected {expected_fingerprint}, got {fingerprint}."
            )

        action = entry.get("action")
        if action is None:
            return None

        return BootstrapPolicyResolution(
            action=action,
            reason=entry.get("reason"),
            fingerprint=expected_fingerprint,
            tables=tuple(entry["tables"]) if entry.get("tables") else None,
        )

    def to_entries(self) -> list[dict[str, Any]]:
        entries = list(self._entries.values())
        entries.sort(
            key=lambda item: (
                item["app"],
                item["migration"],
                item["operation_index"],
                item["nested_path"] or "",
            )
        )
        return entries

    @staticmethod
    def _normalize_tables(tables: Any, source: str, entry_index: int) -> list[str] | None:
        if tables in (None, ""):
            return None
        if not isinstance(tables, list):
            raise ValueError(f"Invalid policy entry #{entry_index} in {source}: 'tables' must be a list.")

        normalized: list[str] = []
        seen: set[str] = set()
        for table in tables:
            table_name = str(table).strip()
            if not table_name:
                raise ValueError(f"Invalid policy entry #{entry_index} in {source}: table names must be non-empty.")
            if not _TABLE_NAME_RE.match(table_name):
                raise ValueError(
                    f"Invalid policy entry #{entry_index} in {source}: table name '{table_name}' is not supported."
                )
            if table_name in seen:
                continue
            seen.add(table_name)
            normalized.append(table_name)
        return normalized


def write_bootstrap_policy_template(
    path: Path,
    app_label: str,
    blockers: list[Any],
) -> None:
    existing_entries: list[dict[str, Any]] = []
    if path.exists():
        existing_raw = yaml.safe_load(path.read_text())
        if isinstance(existing_raw, list):
            existing_entries = [entry for entry in existing_raw if isinstance(entry, dict)]
        elif isinstance(existing_raw, dict):
            existing_entries = [entry for entry in existing_raw.get("entries", []) if isinstance(entry, dict)]

    entry_by_key: dict[tuple[str, str, int, str | None], dict[str, Any]] = {}

    def normalize_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
        app = entry.get("app")
        migration = entry.get("migration")
        operation_index = entry.get("operation_index")
        if not app or not migration or operation_index in (None, ""):
            return None
        try:
            operation_index_int = int(operation_index)
        except (TypeError, ValueError):
            return None
        if operation_index_int < 1:
            return None
        nested_path = entry.get("nested_path")
        nested_path_normalized = None if nested_path in (None, "") else str(nested_path)
        action = entry.get("action")
        action_normalized = None if action in (None, "") else str(action).strip()
        return {
            "app": str(app),
            "migration": str(migration),
            "operation_index": operation_index_int,
            "nested_path": nested_path_normalized,
            "action": action_normalized,
            "fingerprint": None if entry.get("fingerprint") in (None, "") else str(entry.get("fingerprint")),
            "reason": None if entry.get("reason") in (None, "") else str(entry.get("reason")),
            "tables": BootstrapPolicy._normalize_tables(
                tables=entry.get("tables"),
                source="template",
                entry_index=0,
            ),
            "operation_type": None if entry.get("operation_type") in (None, "") else str(entry.get("operation_type")),
        }

    for existing_entry in existing_entries:
        normalized = normalize_entry(existing_entry)
        if normalized is None:
            continue
        key = (
            normalized["app"],
            normalized["migration"],
            normalized["operation_index"],
            normalized["nested_path"],
        )
        entry_by_key[key] = normalized

    for blocker in blockers:
        if blocker.operation_index < 1:
            continue
        key = (app_label, blocker.migration, blocker.operation_index, blocker.nested_path)
        entry = entry_by_key.get(key)
        if entry is None:
            entry = {
                "app": app_label,
                "migration": blocker.migration,
                "operation_index": blocker.operation_index,
                "nested_path": blocker.nested_path,
                "action": None,
                "fingerprint": blocker.fingerprint,
                "reason": blocker.reason,
                "operation_type": blocker.operation_type,
            }
            entry_by_key[key] = entry
            continue

        if entry.get("operation_type") in (None, ""):
            entry["operation_type"] = blocker.operation_type
        if entry.get("fingerprint") in (None, "") and blocker.fingerprint:
            entry["fingerprint"] = blocker.fingerprint
        if entry.get("reason") in (None, ""):
            entry["reason"] = blocker.reason

    merged_entries = list(entry_by_key.values())
    merged_entries.sort(
        key=lambda item: (
            item["app"],
            item["migration"],
            item["operation_index"],
            item["nested_path"] or "",
        )
    )

    payload = {"version": 1, "entries": merged_entries}
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
