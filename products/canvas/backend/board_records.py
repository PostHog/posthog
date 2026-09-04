from collections.abc import Iterable, Sequence
from hashlib import sha256
from typing import cast

from django.contrib.postgres.expressions import ArraySubquery
from django.db.models import Case, F, IntegerField, JSONField, Max, OuterRef, Q, QuerySet, Subquery, Value, When
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, JSONObject

from pydantic import JsonValue

from products.canvas.backend.board_schema import FRAGMENT_PROPERTIES
from products.canvas.backend.models import CanvasBoard, CanvasBoardOp, CanvasBoardRecord

JsonObject = dict[str, JsonValue]


def with_board_records(queryset: QuerySet[CanvasBoard], team_id: int) -> QuerySet[CanvasBoard]:
    records = CanvasBoardRecord.objects.for_team(team_id).filter(board_id=OuterRef("pk"))
    active_sources = (
        CanvasBoardRecord.objects.for_team(team_id)
        .filter(board_id=OuterRef("board_id"), kind="fragment")
        .annotate(ref=KeyTextTransform("codeRef", "value"))
        .values("ref")
    )
    sources = records.filter(kind="source", key__in=Subquery(active_sources)).annotate(
        item=JSONObject(key="key", value="value")
    )
    fragments = records.filter(kind="fragment").order_by("position", "key")
    state = records.filter(kind="state").annotate(item=JSONObject(key="key", value="value"))
    return queryset.defer("snapshot").annotate(
        legacy_snapshot=Case(
            When(records_seq=F("head_seq"), then=Value({}, output_field=JSONField())),
            default=F("snapshot"),
            output_field=JSONField(),
        ),
        record_fragments=ArraySubquery(fragments.values("value")),
        record_sources=ArraySubquery(sources.values("item")),
        record_state=ArraySubquery(state.values("item")),
    )


def hydrate_ops(rows: Sequence[CanvasBoardOp]) -> None:
    if not rows:
        return
    fragments = [fragment for row in rows for fragment in _op_fragments(row.op)]
    refs = {fragment["codeRef"] for fragment in fragments if isinstance(fragment.get("codeRef"), str)}
    if not refs:
        return
    sources = dict(
        CanvasBoardRecord.objects.for_team(rows[0].team_id)
        .filter(board_id=rows[0].board_id, kind="source", key__in=refs)
        .values_list("key", "value")
    )
    for fragment in fragments:
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


class BoardRecords:
    def __init__(self, board: CanvasBoard) -> None:
        self.board = board
        self.queryset = CanvasBoardRecord.objects.for_team(board.team_id).filter(board=board)
        self.records: dict[str, dict[str, CanvasBoardRecord | None]] = {"fragment": {}, "state": {}, "source": {}}
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
        for row in self.queryset.filter(Q(kind="fragment", key__in=fragment_ids) | Q(kind="state", key__in=state_keys)):
            if row.key not in self.records[row.kind]:
                self.records[row.kind][row.key] = row

    def bootstrap(self) -> None:
        if self.board.records_seq is None:
            self.restore(self.board.snapshot, self.board.snapshot_seq)
            self.board.records_seq = self.board.snapshot_seq
        if self.board.records_seq < self.board.head_seq:
            rows = (
                CanvasBoardOp.objects.for_team(self.board.team_id)
                .filter(board=self.board, seq__gt=self.board.records_seq, seq__lte=self.board.head_seq)
                .order_by("seq")
            )
            for row in rows.iterator(chunk_size=500):
                self.prepare([row.op])
                self.apply(row.op, row.seq)

    def source(self, fragment: JsonObject, seq: int) -> JsonObject:
        value = dict(fragment)
        code = value.pop("code", None)
        if isinstance(code, str):
            ref = sha256(code.encode()).hexdigest()
            value["codeRef"] = ref
            self.put("source", ref, code, seq)
        return value

    def put(self, kind: str, key: str, value: JsonValue, seq: int, position: int = 0) -> None:
        self.records[kind][key] = CanvasBoardRecord(
            team_id=self.board.team_id, board=self.board, kind=kind, key=key, value=value, seq=seq, position=position
        )
        self.dirty[kind].add(key)

    def restore(self, snapshot: JsonObject, seq: int) -> JsonObject:
        self.reset = True
        self.records["fragment"].clear()
        self.records["state"].clear()
        self.dirty["fragment"].clear()
        self.dirty["state"].clear()
        fragments = cast(list[JsonObject], snapshot.get("fragments", []))
        normalized = []
        self.top = 0
        for position, fragment in enumerate(fragments, start=-len(fragments)):
            value = self.source(fragment, seq)
            self.put("fragment", str(value["id"]), value, seq, position)
            self.top = max(self.top, cast(int, value.get("z", 0)))
            normalized.append(value)
        for key, state_value in cast(JsonObject, snapshot.get("state", {})).items():
            self.put("state", key, state_value, seq)
        return {**snapshot, "fragments": cast(list[JsonValue], normalized)}

    def apply(self, op: JsonObject, seq: int) -> JsonObject:
        kind = op["type"]
        if kind == "restore":
            return {**op, "snapshot": self.restore(cast(JsonObject, op["snapshot"]), seq)}
        if kind == "add_fragment":
            fragment = self.source(cast(JsonObject, op["fragment"]), seq)
            fragment = {"z": 0, "codeVersion": 1, "surface": "card", "hidden": False, **fragment}
            self.put("fragment", str(fragment["id"]), fragment, seq, seq)
            self.top = None
            return {**op, "fragment": fragment}
        if kind in {"update_fragment", "remove_fragment", "bring_to_front"}:
            key = str(op["id"])
            row = self.records["fragment"].get(key)
            if kind == "remove_fragment":
                self.records["fragment"][key] = None
                self.dirty["fragment"].add(key)
                self.top = None
            elif row is not None:
                value = cast(JsonObject, row.value)
                if kind == "bring_to_front":
                    if self.top is None:
                        unchanged = self.queryset.filter(kind="fragment").exclude(key__in=self.dirty["fragment"])
                        self.top = (
                            0
                            if self.reset
                            else max(0, unchanged.aggregate(top=Max(Cast("value__z", IntegerField())))["top"] or 0)
                        )
                        for record in self.records["fragment"].values():
                            if record is not None:
                                self.top = max(self.top, record.value.get("z", 0))
                    self.top += 1
                    patch: JsonObject = {"z": self.top}
                else:
                    patch = self.source(
                        {
                            key: item
                            for key, item in cast(JsonObject, op["patch"]).items()
                            if key in {*FRAGMENT_PROPERTIES, "codeRef"} and key != "id"
                        },
                        seq,
                    )
                    op = {**op, "patch": dict(patch)}
                    if "codeRef" in patch and patch["codeRef"] != value.get("codeRef") and "codeVersion" not in patch:
                        patch["codeVersion"] = cast(int, value.get("codeVersion", 1)) + 1
                    if "z" in patch:
                        self.top = None
                self.put("fragment", key, {**value, **patch}, seq, row.position)
            return op
        key = str(op["key"])
        if kind == "set_state":
            if op["value"] is None:
                self.records["state"][key] = None
                self.dirty["state"].add(key)
            else:
                self.put("state", key, op["value"], seq)
        elif kind == "edit_field":
            row = self.records["state"].get(key)
            field = row.value if row is not None else None
            if field is None:
                field = {"__field": op["kind"], "entries": {}, "removed": []}
            if (
                not isinstance(field, dict)
                or field.get("__field") != op["kind"]
                or not isinstance(field.get("entries"), dict)
                or not isinstance(field.get("removed"), list)
            ):
                return op
            entries = dict(field["entries"])
            removed = dict.fromkeys(entry_id for entry_id in field["removed"] if isinstance(entry_id, str))
            for entry_id in cast(list[str], op.get("remove", [])):
                removed[entry_id] = None
                entries.pop(entry_id, None)
            for item in cast(list[JsonObject], op.get("insert", [])):
                entry_id = str(item["id"])
                if entry_id not in removed:
                    entries[entry_id] = {"k": item["k"], "v": item["v"]}
            self.put("state", key, {"__field": op["kind"], "entries": entries, "removed": list(removed)}, seq)
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
            unique_fields=["board", "kind", "key"],
            update_fields=["value", "seq", "position"],
        )
