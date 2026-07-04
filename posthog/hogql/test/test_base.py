import gc
import copy
import weakref
import dataclasses
from typing import Any

import pytest
from posthog.test.base import BaseTest

import pydantic
from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.base import AST, Type
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import resolve_types

# --- cycle-safe helpers (resolved ASTs contain FieldType <-> SelectQueryType cycles) ---


def _structural_equal(a: Any, b: Any, seen: set | None = None) -> bool:
    if a is b:
        return True
    if seen is None:
        seen = set()
    key = (id(a), id(b))
    if key in seen:
        return True
    seen.add(key)
    if isinstance(a, AST):
        if type(a) is not type(b):
            return False
        return all(
            _structural_equal(getattr(a, f.name, None), getattr(b, f.name, None), seen) for f in dataclasses.fields(a)
        )
    if isinstance(a, list):
        return isinstance(b, list) and len(a) == len(b) and all(_structural_equal(x, y, seen) for x, y in zip(a, b))
    if isinstance(a, tuple):
        return isinstance(b, tuple) and len(a) == len(b) and all(_structural_equal(x, y, seen) for x, y in zip(a, b))
    if isinstance(a, dict):
        # Keys, not just positional values: a key swap/corruption (column/alias names in resolved ASTs) must fail.
        if not isinstance(b, dict) or a.keys() != b.keys():
            return False
        return all(_structural_equal(a[k], b[k], seen) for k in a)
    return bool(a == b)


def _assert_independent(original: Any, clone: Any, seen: set | None = None) -> None:
    if seen is None:
        seen = set()
    if id(original) in seen:
        return
    seen.add(id(original))
    if isinstance(original, AST):
        assert original is not clone, f"clone shares AST node {type(original).__name__} with the original"
        for f in dataclasses.fields(original):
            _assert_independent(getattr(original, f.name, None), getattr(clone, f.name, None), seen)
    elif isinstance(original, list):
        assert original is not clone, "clone shares a list with the original"
        assert len(original) == len(clone), "clone changed a list's length"
        for x, y in zip(original, clone):
            _assert_independent(x, y, seen)
    elif isinstance(original, tuple):
        # stdlib shares an unchanged immutable tuple (safe -- no mutable state); a cloned element forces a rebuild.
        if original is clone:
            return
        assert len(original) == len(clone), "clone changed a tuple's length"
        for x, y in zip(original, clone):
            _assert_independent(x, y, seen)
    elif isinstance(original, dict):
        assert original is not clone, "clone shares a dict with the original"
        assert len(original) == len(clone), "clone changed a dict's length"
        for (ok, ov), (ck, cv) in zip(original.items(), clone.items()):
            _assert_independent(ok, ck, seen)  # keys too (str keys are atomic no-ops; container keys get checked)
            _assert_independent(ov, cv, seen)
    elif isinstance(original, set):
        assert original is not clone, "clone shares a set with the original"  # frozenset is immutable, sharing is fine
    elif isinstance(original, pydantic.BaseModel):
        # Embedded non-AST models (database Tables/joins) must be deep-copied, not shared.
        assert original is not clone, f"clone shares {type(original).__name__} with the original"
        for name in type(original).model_fields:
            _assert_independent(getattr(original, name, None), getattr(clone, name, None), seen)


def _count_distinct_nodes(node: Any) -> int:
    seen: set[int] = set()

    def walk(n: Any) -> None:
        if isinstance(n, AST):
            if id(n) in seen:
                return
            seen.add(id(n))
            for f in dataclasses.fields(n):
                walk(getattr(n, f.name, None))
        elif isinstance(n, list | tuple):
            for x in n:
                walk(x)
        elif isinstance(n, dict):
            for v in n.values():
                walk(v)

    walk(node)
    return len(seen)


def _stock_deepcopy(node: Any) -> Any:
    # Drop the fast path so copy.deepcopy uses stdlib; mutates AST globally (restored in finally), single-threaded only.
    impl = AST.__dict__["__deepcopy__"]
    del AST.__deepcopy__
    try:
        return copy.deepcopy(node)
    finally:
        AST.__deepcopy__ = impl  # type: ignore[method-assign]


def _assert_faithful_clone(original: Any) -> Any:
    clone = copy.deepcopy(original)
    assert _structural_equal(clone, original)
    assert _structural_equal(clone, _stock_deepcopy(original))  # parity with stdlib, not just self-consistency
    _assert_independent(original, clone)
    assert _count_distinct_nodes(clone) == _count_distinct_nodes(original)
    return clone


# --- targeted behavior ---


def test_deepcopy_is_independent_of_original():
    node = ast.Field(chain=["a", "b"])
    clone = copy.deepcopy(node)
    clone.chain.append("c")
    assert node.chain == ["a", "b"]
    assert clone is not node
    assert clone.chain is not node.chain


def test_deepcopy_preserves_shared_subtrees():
    shared = ast.Constant(value=1)
    node = ast.Tuple(exprs=[shared, shared])
    clone = copy.deepcopy(node)
    assert clone.exprs[0] is clone.exprs[1]
    assert clone.exprs[0] is not shared


def test_deepcopy_preserves_resolved_type_cycle():
    select_type = ast.SelectQueryType(aliases={}, columns={}, tables={}, anonymous_tables=[])
    field_type = ast.FieldType(name="x", table_type=select_type)
    select_type.columns = {"x": field_type}
    node = ast.Field(chain=["x"], type=field_type)

    clone = copy.deepcopy(node)

    cloned_type = clone.type
    assert isinstance(cloned_type, ast.FieldType)
    assert cloned_type is not field_type
    cloned_table_type = cloned_type.table_type
    assert isinstance(cloned_table_type, ast.SelectQueryType)
    assert cloned_table_type.columns["x"] is cloned_type


def test_deepcopy_handles_self_referential_container_value():
    value: list = [1]
    value.append(value)

    clone = copy.deepcopy(ast.Constant(value=value))

    assert clone.value is not value
    assert clone.value[1] is clone.value


def test_deepcopy_handles_tuple_rooted_cycle_like_stdlib():
    # A cycle re-entering a tuple must keep the tuple's identity, like stdlib (returns the in-progress copy).
    inner: list = []
    cyclic_tuple = (inner,)
    inner.append(cyclic_tuple)

    clone = copy.deepcopy(ast.Constant(value=cyclic_tuple))

    assert clone.value is not cyclic_tuple
    assert clone.value[0][0] is clone.value  # back-reference resolves to the cloned tuple
    assert clone.value[0] is not inner


def test_deepcopy_deep_copies_dict_fields():
    node = ast.SelectQueryType(aliases={}, columns={"a": ast.IntegerType()}, tables={}, anonymous_tables=[])
    clone = copy.deepcopy(node)
    assert clone.columns is not node.columns
    assert clone.columns["a"] is not node.columns["a"]
    assert isinstance(clone.columns["a"], ast.IntegerType)


def test_deepcopy_clears_nothing_and_matches_structure():
    node = ast.And(
        exprs=[
            ast.CompareOperation(
                left=ast.Field(chain=["a"]), right=ast.Constant(value=1), op=ast.CompareOperationOp.Eq
            ),
            ast.Constant(value=True),
        ]
    )
    clone = copy.deepcopy(node)
    assert isinstance(clone, ast.And)
    assert clone is not node
    assert clone.exprs[0] is not node.exprs[0]
    first, second = clone.exprs[0], clone.exprs[1]
    assert isinstance(first, ast.CompareOperation)
    assert first.op == ast.CompareOperationOp.Eq
    assert isinstance(second, ast.Constant)
    assert second.value is True


def test_deepcopy_returns_ast_subclass_instance():
    assert isinstance(copy.deepcopy(ast.Constant(value=1)), ast.Constant)
    assert isinstance(copy.deepcopy(ast.Field(chain=["x"])), AST)


# --- childless types surface an exposed error, not an internal one, from any call site ---


def test_type_get_child_on_childless_type_raises_exposed_error():
    # Accessing a property on a type with no children (e.g. a scalar column alias shadowing a table
    # field) reaches Type.get_child. It must raise an exposed QueryError so field resolution fails
    # cleanly, rather than an internal NotImplementedError that escapes to the query runner.
    context = HogQLContext(team_id=1)
    with pytest.raises(ExposedHogQLError, match="Cannot access property.*renaming the alias"):
        Type().get_child("foo", context)
    with pytest.raises(ExposedHogQLError):
        Type().has_child("foo", context)


# --- corpus: a broad set of parsed queries cloned and checked for faithfulness ---

_CORPUS = [
    "SELECT 1",
    "SELECT 1 + 2 * 3 - 4 / 2",
    "SELECT 1.5, -3, 0, true, false, null",
    "SELECT 'hello', 'with ''quotes'''",
    "SELECT 1 = 1, 2 != 3, 4 < 5, 6 > 7, 8 <= 9, 10 >= 11",
    "SELECT 1 AND 0, 1 OR 0, NOT 1",
    "SELECT 1 IN (1, 2, 3), 4 NOT IN (5, 6)",
    "SELECT 'a' LIKE '%b%', 'c' ILIKE '%D%', 'e' NOT LIKE 'f'",
    "SELECT 5 = 5, 1e10, 1.5e-3",
    "SELECT event, timestamp, distinct_id FROM events",
    "SELECT properties.foo, properties.bar.baz FROM events",
    "SELECT person.properties.email FROM events",
    "SELECT a.b.c.d FROM events",
    "SELECT arr[1], arr[2 + 3] FROM events",
    "SELECT mapValue['key'] FROM events",
    "SELECT count(), count(distinct distinct_id) FROM events",
    "SELECT sum(value), avg(value), min(value), max(value) FROM events",
    "SELECT quantile(0.95)(value) FROM events",
    "SELECT sumIf(value, event = 'x'), countIf(value > 0) FROM events",
    "SELECT toString(123), toInt('5'), toFloat('1.5') FROM events",
    "SELECT coalesce(a, b, c), ifNull(a, 0), nullIf(a, b) FROM events",
    "SELECT concat('a', 'b', 'c'), substring('hello', 1, 3) FROM events",
    "SELECT now(), today(), toStartOfDay(timestamp), toStartOfWeek(timestamp) FROM events",
    "SELECT dateDiff('day', timestamp, now()) FROM events",
    "SELECT isNull(a), isNotNull(b) FROM events",
    "SELECT arrayMap(x -> x * 2, [1, 2, 3])",
    "SELECT arrayFilter(x -> x > 1, [1, 2, 3])",
    "SELECT arrayMap((x, y) -> x + y, [1, 2], [3, 4])",
    "SELECT [1, 2, 3], [], ['a', 'b']",
    "SELECT (1, 2, 3), ('a', true, null)",
    "SELECT if(1 > 0, 'yes', 'no')",
    "SELECT multiIf(a = 1, 'one', a = 2, 'two', 'other') FROM events",
    "SELECT CASE WHEN a = 1 THEN 'x' WHEN a = 2 THEN 'y' ELSE 'z' END FROM events",
    "SELECT CASE a WHEN 1 THEN 'x' ELSE 'y' END FROM events",
    "SELECT CAST(value AS Int64) FROM events",
    "SELECT value::String FROM events",
    "SELECT assumeNotNull(value) FROM events",
    "SELECT -value, NOT value FROM events",
    "SELECT value % 3 FROM events",
    "SELECT event, count() FROM events WHERE timestamp > now() - INTERVAL 7 DAY GROUP BY event",
    "SELECT event, count() c FROM events GROUP BY event HAVING c > 10 ORDER BY c DESC LIMIT 5",
    "SELECT event FROM events ORDER BY timestamp ASC, event DESC",
    "SELECT event FROM events LIMIT 10 OFFSET 20",
    "SELECT event FROM events LIMIT 5 BY distinct_id",
    "SELECT DISTINCT event FROM events",
    "SELECT event FROM events ORDER BY count() DESC LIMIT 3 WITH TIES",
    "SELECT e.event, p.id FROM events e JOIN persons p ON e.person_id = p.id",
    "SELECT e.event FROM events e LEFT JOIN persons p ON e.person_id = p.id",
    "SELECT e.event FROM events e RIGHT JOIN persons p ON e.person_id = p.id",
    "SELECT e.event FROM events e FULL JOIN persons p ON e.person_id = p.id",
    "SELECT e.event FROM events e CROSS JOIN persons p",
    "SELECT e.event FROM events e INNER JOIN persons p ON e.person_id = p.id",
    "SELECT a.x FROM t1 a JOIN t2 b ON a.id = b.id JOIN t3 c ON b.id = c.id",
    "SELECT x FROM (SELECT 1 AS x)",
    "SELECT x FROM (SELECT event AS x FROM events) sub",
    "WITH cte AS (SELECT event FROM events) SELECT event FROM cte",
    "WITH 1 AS x SELECT x + 1",
    "SELECT event FROM events WHERE distinct_id IN (SELECT distinct_id FROM events WHERE event = 'x')",
    "SELECT (SELECT count() FROM events) AS total",
    "SELECT 1 UNION ALL SELECT 2",
    "SELECT event FROM events SAMPLE 0.1",
    "SELECT event, count() OVER (PARTITION BY event ORDER BY timestamp) FROM events",
    "SELECT sum(value) OVER w FROM events WINDOW w AS (PARTITION BY event)",
    "SELECT event, count() OVER (ORDER BY timestamp ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) FROM events",
    "SELECT 1 AS a, 2 AS b, 3 AS c",
    "SELECT * FROM events",
    "SELECT e.* FROM events e",
    "SELECT count(*) FROM events",
    "SELECT 'emoji 🎉', 'tab\there'",
    "SELECT toDateTime('2023-01-01 00:00:00')",
    "SELECT today() - 7",
    "SELECT 5 BETWEEN 1 AND 10, 5 NOT BETWEEN 1 AND 10",
    "SELECT tuple(1, 2, 3).1 FROM events",
    "SELECT event FROM events WHERE properties.x = 'a' AND properties.y > 1 OR NOT properties.z",
    "SELECT length(arrayMap(x -> x + 1, range(1, 10)))",
    "SELECT groupArray(event), groupUniqArray(distinct_id) FROM events",
    "SELECT event, count() FROM events GROUP BY event ORDER BY 2 DESC",
    "SELECT 1 AS x, x + 1 AS y, y * 2 AS z",
    "SELECT replaceAll(event, 'a', 'b'), splitByChar(',', event) FROM events",
    "SELECT JSONExtractString(properties, 'key') FROM events",
    "SELECT toStartOfInterval(timestamp, INTERVAL 1 HOUR) FROM events",
    "SELECT event FROM events WHERE timestamp BETWEEN now() - INTERVAL 1 DAY AND now()",
    "SELECT countIf(event = 'a') / countIf(event = 'b') AS ratio FROM events",
    "SELECT and(a > 1, b < 2, c = 3) FROM events",
    "SELECT or(a, b, c) FROM events",
    "SELECT plus(1, 2), minus(5, 3), multiply(2, 4), divide(10, 2)",
    "SELECT event FROM events WHERE event IN (SELECT event FROM events) AND timestamp > now()",
    "SELECT nullIf(a, 0), greatest(a, b), least(a, b) FROM events",
    "SELECT event, row_number() OVER (PARTITION BY event ORDER BY timestamp DESC) AS rn FROM events",
    "SELECT arraySort(x -> -x, [3, 1, 2])",
    "SELECT date_trunc('month', timestamp) FROM events",
    "SELECT event FROM events WHERE has([1, 2, 3], 2)",
    "SELECT indexOf(['a', 'b', 'c'], 'b')",
    "SELECT event FROM events PREWHERE event = 'x' WHERE timestamp > now()",
    "SELECT a, b, c FROM events GROUP BY a, b, c HAVING count() > 1",
    "SELECT 1 WHERE 1 = 1",
    "SELECT trim(BOTH ' ' FROM '  x  ')",
    "SELECT event FROM events FINAL",
    "SELECT coalesce(properties.a, properties.b, 'default') AS v FROM events",
    "SELECT event, count() AS c FROM events GROUP BY event ORDER BY c DESC LIMIT 10 OFFSET 5",
]


@pytest.mark.parametrize("query", _CORPUS)
def test_deepcopy_corpus_is_faithful_and_independent(query):
    original = parse_select(query)
    _assert_faithful_clone(original)


# --- every concrete AST node type clones all of its fields (self-maintaining over new nodes) ---


def _all_concrete_ast_classes():
    def subclasses(cls):
        for sub in cls.__subclasses__():
            yield sub
            yield from subclasses(sub)

    return sorted(
        {c for c in subclasses(AST) if dataclasses.is_dataclass(c)},
        key=lambda c: c.__name__,
    )


def test_node_coverage_guard_sees_all_node_types():
    # __subclasses__() sees only imported classes; this floor catches a node module dropping out of the import graph.
    assert len(_all_concrete_ast_classes()) >= 100


def _field_marker(i: int) -> Any:
    # Exercises the list, dict, tuple, AST-recursion and scalar branches of _clone_value for every field.
    return [i, {"k": i}, (i,), ast.Constant(value=i)]


@pytest.mark.parametrize("cls", _all_concrete_ast_classes(), ids=lambda c: c.__name__)
def test_deepcopy_covers_every_field_of_every_node_type(cls):
    instance = cls.__new__(cls)
    node_fields = dataclasses.fields(cls)
    for i, f in enumerate(node_fields):
        # start/end are copied by reference, so keep them atomic; every other field gets a deep, mixed-type marker.
        setattr(instance, f.name, i if f.name in ("start", "end") else _field_marker(i))

    clone = copy.deepcopy(instance)

    for i, f in enumerate(node_fields):
        expected = i if f.name in ("start", "end") else _field_marker(i)
        assert getattr(clone, f.name) == expected, f"{cls.__name__}.{f.name} not copied"
    _assert_independent(instance, clone)  # every deep-copied field is a distinct object graph


# --- Constant.value covers arbitrary Python payloads ---

_CONSTANT_VALUES = [
    0,
    1,
    -1,
    3.14,
    "string",
    "",
    True,
    False,
    None,
    b"bytes",
    [1, 2, 3],
    [],
    {"a": 1, "b": 2},
    {},
    (1, 2, 3),
    {1, 2, 3},
    frozenset({1, 2}),
    [1, [2, {"k": 3}], (4, 5)],
    {"nested": [1, 2], "deep": {"x": [3]}},
    [None, True, "x", 1.5],
]


@pytest.mark.parametrize("value", _CONSTANT_VALUES, ids=lambda v: repr(v)[:24])
def test_deepcopy_constant_value(value):
    original = ast.Constant(value=value)
    clone = copy.deepcopy(original)
    assert clone.value == value
    if isinstance(value, list | dict | set):
        assert clone.value is not value
        assert clone.value == original.value


def test_deepcopy_constant_nested_value_is_deeply_independent():
    inner: list = [1, 2]
    original = ast.Constant(value={"k": inner})
    clone = copy.deepcopy(original)
    clone.value["k"].append(3)
    assert original.value["k"] == [1, 2]


# --- the clone retains no reference back into the original ---


def test_deepcopy_does_not_retain_original():
    class _Marker:
        pass

    marker = _Marker()
    original = ast.Tuple(exprs=[ast.Constant(value=marker)])
    clone = copy.deepcopy(original)

    cloned_constant = clone.exprs[0]
    assert isinstance(cloned_constant, ast.Constant)
    assert cloned_constant.value is not marker  # holds a copy, not the original payload

    ref = weakref.ref(marker)
    del original, marker
    gc.collect()
    assert ref() is None  # nothing in the clone keeps the original payload alive


# --- resolved ASTs (cyclic type graphs) clone faithfully; exercised in prod via event_sessions ---


class TestDeepcopyResolved(BaseTest):
    def setUp(self):
        self.database = Database.create_for(team=self.team)
        self.context = HogQLContext(database=self.database, team_id=self.team.pk, enable_select_queries=True)

    def _resolve(self, query: str) -> Any:
        return resolve_types(parse_select(query), self.context, dialect="clickhouse")

    @parameterized.expand(
        [
            ("SELECT event, events.timestamp FROM events WHERE events.event = 'test'",),
            ("SELECT event, count() FROM events GROUP BY event HAVING count() > 1",),
            ("SELECT x FROM (SELECT event AS x FROM events) sub",),
        ]
    )
    def test_resolved_clone_matches_stock_and_preserves_type_graph(self, query: str):
        resolved = self._resolve(query)
        stock = _stock_deepcopy(resolved)
        clone = copy.deepcopy(resolved)

        assert _structural_equal(clone, stock)
        assert _count_distinct_nodes(clone) == _count_distinct_nodes(stock)
        _assert_independent(resolved, clone)
