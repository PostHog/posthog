from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from hashlib import sha256
from typing import Protocol, TypedDict, cast

from django.contrib.postgres.expressions import ArraySubquery
from django.db.models import BigIntegerField, Max, OuterRef, Q, QuerySet, Subquery
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, JSONObject

from pydantic import JsonValue
from rest_framework.exceptions import ValidationError

from products.canvas.backend.facade.enums import SketchpadRecordKind
from products.canvas.backend.models import Sketchpad, SketchpadOp, SketchpadRecord
from products.canvas.backend.sketchpad.schema import FRAGMENT_PROPERTIES

JsonObject = dict[str, JsonValue]


class RecordItem(TypedDict):
    key: str
    value: JsonValue


class SketchpadRecordAnnotations(Protocol):
    record_fragments: list[JsonObject]
    record_sources: list[RecordItem]
    record_state: list[RecordItem]


def with_sketchpad_records(queryset: QuerySet[Sketchpad], team_id: int) -> QuerySet[Sketchpad]:
    records = SketchpadRecord.objects.for_team(team_id).filter(sketchpad_id=OuterRef("pk"))
    active_sources = (
        SketchpadRecord.objects.for_team(team_id)
        .filter(sketchpad_id=OuterRef("sketchpad_id"), kind=SketchpadRecordKind.FRAGMENT)
        .annotate(ref=KeyTextTransform("codeRef", "value"))
        .values("ref")
    )
    sources = records.filter(kind=SketchpadRecordKind.SOURCE, key__in=Subquery(active_sources)).annotate(
        item=JSONObject(key="key", value="value")
    )
    fragments = records.filter(kind=SketchpadRecordKind.FRAGMENT).order_by("position", "key")
    state = records.filter(kind=SketchpadRecordKind.STATE).annotate(item=JSONObject(key="key", value="value"))
    return queryset.annotate(
        record_fragments=ArraySubquery(fragments.values("value")),
        record_sources=ArraySubquery(sources.values("item")),
        record_state=ArraySubquery(state.values("item")),
    )


def op_sources(rows: Sequence[SketchpadOp]) -> dict[str, JsonValue]:
    if not rows:
        return {}
    fragments = [fragment for row in rows for fragment in _op_fragments(row.op)]
    refs = {fragment["codeRef"] for fragment in fragments if isinstance(fragment.get("codeRef"), str)}
    if not refs:
        return {}
    return dict(
        SketchpadRecord.objects.for_team(rows[0].team_id)
        .filter(sketchpad_id=rows[0].sketchpad_id, kind=SketchpadRecordKind.SOURCE, key__in=refs)
        .values_list("key", "value")
    )


def hydrate_ops(rows: Sequence[SketchpadOp]) -> None:
    sources = op_sources(rows)
    for fragment in (fragment for row in rows for fragment in _op_fragments(row.op)):
        ref = fragment.pop("codeRef", None)
        if isinstance(ref, str):
            fragment["code"] = sources[ref]


def _op_fragments(op: JsonObject) -> Iterable[JsonObject]:
    if op["type"] == "add_fragment":
        yield cast(JsonObject, op["fragment"])
    elif op["type"] == "update_fragment":
        yield cast(JsonObject, op["patch"])
    elif op["type"] == "restore":
        yield from cast(list[JsonObject], cast(JsonObject, op["snapshot"]).get("fragments", []))


def merge_field(field: JsonValue, op: JsonObject) -> JsonObject:
    if "initialValue" in op and not isinstance(field, dict):
        if json.dumps(field, sort_keys=True) != json.dumps(op["initialValue"], sort_keys=True):
            raise ValidationError("This value changed. Reload the sketchpad before you edit it.")
        field = None
    if field is None:
        field = {"__field": op["kind"], "entries": {}, "removed": []}
    error = "This value is not a shared field. Reload the sketchpad before you edit it."
    if not isinstance(field, dict) or field.get("__field") != op["kind"]:
        raise ValidationError(error)
    field_entries = field.get("entries")
    field_removed = field.get("removed")
    if not isinstance(field_entries, dict):
        raise ValidationError(error)
    if not isinstance(field_removed, list):
        raise ValidationError(error)
    entries = dict(field_entries)
    removed = dict.fromkeys(entry_id for entry_id in field_removed if isinstance(entry_id, str))
    for entry_id in cast(list[str], op.get("remove", [])):
        removed[entry_id] = None
        entries.pop(entry_id, None)
    for item in cast(list[JsonObject], op.get("insert", [])):
        entry_id = str(item["id"])
        if "initialValue" in op and entry_id in entries:
            continue
        if entry_id not in removed:
            entries[entry_id] = {"k": item["k"], "v": item["v"]}
    return {"__field": op["kind"], "entries": entries, "removed": list(removed)}


class SketchpadRecords:
    def __init__(self, sketchpad: Sketchpad) -> None:
        self.sketchpad = sketchpad
        self.queryset = SketchpadRecord.objects.for_team(sketchpad.team_id).filter(sketchpad=sketchpad)
        self.records: dict[str, dict[str, SketchpadRecord | None]] = {"fragment": {}, "state": {}, "source": {}}
        self.dirty: dict[str, set[str]] = {kind: set() for kind in self.records}
        self.reset = False
        self.top: int | None = None

    def prepare(self, ops: Sequence[JsonObject]) -> None:
        if self.reset:
            return
        fragment_ids = {
            str(op["id"]) for op in ops if op["type"] in {"update_fragment", "remove_fragment", "bring_to_front"}
        }
        state_keys = {str(op["key"]) for op in ops if op["type"] == "edit_field"}
        for row in self.queryset.filter(
            Q(kind=SketchpadRecordKind.FRAGMENT, key__in=fragment_ids)
            | Q(kind=SketchpadRecordKind.STATE, key__in=state_keys)
        ):
            if row.key not in self.records[row.kind]:
                self.records[row.kind][row.key] = row

    def source(self, fragment: JsonObject) -> JsonObject:
        value = dict(fragment)
        code = value.pop("code", None)
        if isinstance(code, str):
            ref = sha256(code.encode()).hexdigest()
            value["codeRef"] = ref
            self.put(SketchpadRecordKind.SOURCE, ref, code)
        return value

    def put(self, kind: SketchpadRecordKind, key: str, value: JsonValue, position: int = 0) -> None:
        self.records[kind][key] = SketchpadRecord(
            team_id=self.sketchpad.team_id,
            sketchpad=self.sketchpad,
            kind=kind,
            key=key,
            value=value,
            position=position,
        )
        self.dirty[kind].add(key)

    def restore(self, snapshot: JsonObject) -> JsonObject:
        self.reset = True
        self.records["fragment"].clear()
        self.records["state"].clear()
        self.dirty["fragment"].clear()
        self.dirty["state"].clear()
        fragments = cast(list[JsonObject], snapshot.get("fragments", []))
        normalized = []
        self.top = 0
        for position, fragment in enumerate(fragments, start=-len(fragments)):
            value = self.source(fragment)
            self.put(SketchpadRecordKind.FRAGMENT, str(value["id"]), value, position)
            self.top = max(self.top, cast(int, value.get("z", 0)))
            normalized.append(value)
        for key, state_value in cast(JsonObject, snapshot.get("state", {})).items():
            self.put(SketchpadRecordKind.STATE, key, state_value)
        return {**snapshot, "fragments": cast(list[JsonValue], normalized)}

    def apply(self, op: JsonObject, seq: int) -> JsonObject:
        handlers = {
            "restore": self._apply_restore,
            "add_fragment": self._apply_add_fragment,
            "update_fragment": self._apply_update_fragment,
            "remove_fragment": self._apply_remove_fragment,
            "bring_to_front": self._apply_bring_to_front,
            "set_state": self._apply_set_state,
            "edit_field": self._apply_edit_field,
        }
        return handlers[str(op["type"])](op, seq)

    def _apply_restore(self, op: JsonObject, seq: int) -> JsonObject:
        if op.get("expectedSeq") != seq - 1:
            raise ValidationError("The sketchpad changed. Reload it before you restore or undo an edit.")
        return {**op, "snapshot": self.restore(cast(JsonObject, op["snapshot"]))}

    def _apply_add_fragment(self, op: JsonObject, seq: int) -> JsonObject:
        fragment = self.source(cast(JsonObject, op["fragment"]))
        fragment = {"z": 0, "codeVersion": 1, "surface": "card", "hidden": False, **fragment}
        self.put(SketchpadRecordKind.FRAGMENT, str(fragment["id"]), fragment, seq)
        self.top = None
        return {**op, "fragment": fragment}

    def _apply_remove_fragment(self, op: JsonObject, seq: int) -> JsonObject:
        key = str(op["id"])
        self.records["fragment"][key] = None
        self.dirty["fragment"].add(key)
        self.top = None
        return op

    def _apply_update_fragment(self, op: JsonObject, seq: int) -> JsonObject:
        key = str(op["id"])
        row = self.records["fragment"].get(key)
        if row is None:
            return op
        value = cast(JsonObject, row.value)
        patch = self.source(
            {
                key: item
                for key, item in cast(JsonObject, op["patch"]).items()
                if key in {*FRAGMENT_PROPERTIES, "codeRef"} and key != "id"
            }
        )
        normalized = {**op, "patch": dict(patch)}
        code_changed = "codeRef" in patch and patch["codeRef"] != value.get("codeRef")
        if code_changed and "codeVersion" not in patch:
            patch["codeVersion"] = cast(int, value.get("codeVersion", 1)) + 1
        if "z" in patch:
            self.top = None
        self.put(SketchpadRecordKind.FRAGMENT, key, {**value, **patch}, row.position)
        return normalized

    def _next_z(self) -> int:
        if self.top is None:
            unchanged = self.queryset.filter(kind=SketchpadRecordKind.FRAGMENT).exclude(key__in=self.dirty["fragment"])
            self.top = (
                0
                if self.reset
                else max(0, unchanged.aggregate(top=Max(Cast("value__z", BigIntegerField())))["top"] or 0)
            )
            for record in self.records["fragment"].values():
                if record is not None:
                    self.top = max(self.top, record.value.get("z", 0))
        if self.top >= 2**53 - 1:
            raise ValidationError("The sketchpad has reached its layer limit.")
        self.top += 1
        return self.top

    def _apply_bring_to_front(self, op: JsonObject, seq: int) -> JsonObject:
        key = str(op["id"])
        row = self.records["fragment"].get(key)
        if row is not None:
            self.put(SketchpadRecordKind.FRAGMENT, key, {**row.value, "z": self._next_z()}, row.position)
        return op

    def _apply_set_state(self, op: JsonObject, seq: int) -> JsonObject:
        key = str(op["key"])
        if op["value"] is None:
            self.records["state"][key] = None
            self.dirty["state"].add(key)
        else:
            self.put(SketchpadRecordKind.STATE, key, op["value"])
        return op

    def _apply_edit_field(self, op: JsonObject, seq: int) -> JsonObject:
        key = str(op["key"])
        row = self.records["state"].get(key)
        field = row.value if row is not None else None
        self.put(SketchpadRecordKind.STATE, key, merge_field(field, op))
        return op

    def save(self) -> None:
        if self.reset:
            self.queryset.filter(kind__in=["fragment", "state"]).delete()
        writes = []
        for kind in ("fragment", "state"):
            deleted = []
            for key in self.dirty[kind]:
                row = self.records[kind][key]
                if row is None:
                    deleted.append(key)
                else:
                    writes.append(row)
            if deleted and not self.reset:
                self.queryset.filter(kind=kind, key__in=deleted).delete()
        self.queryset.bulk_create(
            [row for row in self.records["source"].values() if row is not None], ignore_conflicts=True
        )
        self.queryset.bulk_create(
            writes,
            update_conflicts=True,
            unique_fields=["sketchpad", "kind", "key"],
            update_fields=["value", "updated_at", "position"],
        )
        if (
            self.reset
            or self.dirty["source"]
            or any(self.records["fragment"].get(key) is None for key in self.dirty["fragment"])
        ):
            sources = (
                self.queryset.filter(kind=SketchpadRecordKind.FRAGMENT)
                .annotate(ref=KeyTextTransform("codeRef", "value"))
                .values("ref")
            )
            self.queryset.filter(kind=SketchpadRecordKind.COMPILED).exclude(key__in=sources).delete()
