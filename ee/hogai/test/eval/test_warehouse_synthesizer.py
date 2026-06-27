"""Unit tests for the pure warehouse synthesizer — no Django, no infra."""

from __future__ import annotations

from dataclasses import astuple

from ee.hogai.eval.sandboxed.data_warehouse.synthesizer import (
    CHAIN_NEEDLE_HOP3,
    DESC_NEEDLE_PHRASE,
    DESC_NEEDLE_TABLE,
    REL_NEEDLE_SOURCE,
    REL_NEEDLE_TARGET,
    RELEVANCY_NEEDLE_CURRENT,
    RELEVANCY_NEEDLE_STALE,
    RETRIEVAL_NEEDLE_ANSWER,
    RETRIEVAL_NEEDLE_TABLE,
    TYPE_NEEDLE_COLUMN,
    TYPE_NEEDLE_TABLE,
    VIEW_NEEDLE_NAME,
    WarehouseSchemaSynthesizer,
)


def test_generation_is_deterministic():
    first = WarehouseSchemaSynthesizer(seed=7).generate()
    second = WarehouseSchemaSynthesizer(seed=7).generate()
    assert [astuple(t) for t in first.tables] == [astuple(t) for t in second.tables]
    assert [astuple(v) for v in first.views] == [astuple(v) for v in second.views]
    assert [astuple(j) for j in first.joins] == [astuple(j) for j in second.joins]


def test_catalog_is_large_and_unique():
    warehouse = WarehouseSchemaSynthesizer(noise_table_count=250).generate()
    names = [t.name for t in warehouse.tables]
    assert len(names) == len(set(names))
    # ~250 noise + 5 needle tables; allow slack for dedup collisions in noise.
    assert len(names) >= 200


def test_decimal_column_is_unique_to_the_type_needle():
    warehouse = WarehouseSchemaSynthesizer().generate()
    decimal_owners = [t.name for t in warehouse.tables for c in t.columns if c.hogql == "DecimalDatabaseField"]
    assert decimal_owners == [TYPE_NEEDLE_TABLE]
    type_needle = next(t for t in warehouse.tables if t.name == TYPE_NEEDLE_TABLE)
    assert any(c.name == TYPE_NEEDLE_COLUMN for c in type_needle.columns)


def test_description_needle_carries_distinguishing_phrase():
    warehouse = WarehouseSchemaSynthesizer().generate()
    table = next(t for t in warehouse.tables if t.name == DESC_NEEDLE_TABLE)
    assert table.description is not None and DESC_NEEDLE_PHRASE in table.description


def test_relationship_endpoints_exist_and_are_joined():
    warehouse = WarehouseSchemaSynthesizer().generate()
    names = {t.name for t in warehouse.tables}
    assert {REL_NEEDLE_SOURCE, REL_NEEDLE_TARGET}.issubset(names)
    assert any(j.source_table == REL_NEEDLE_SOURCE and j.joining_table == REL_NEEDLE_TARGET for j in warehouse.joins)


def test_view_needle_present_among_views():
    warehouse = WarehouseSchemaSynthesizer().generate()
    assert any(v.name == VIEW_NEEDLE_NAME for v in warehouse.views)


def test_retrieval_needle_is_queryable_with_duck_typed_content():
    warehouse = WarehouseSchemaSynthesizer().generate()
    queryable = [t for t in warehouse.tables if t.queryable]
    assert [t.name for t in queryable] == [RETRIEVAL_NEEDLE_TABLE]
    needle = queryable[0]
    # All columns are declared String even though content is numeric/JSON.
    assert all(c.hogql == "StringDatabaseField" for c in needle.columns)
    # The secret answer lives in exactly one row's payload, and string-max != numeric-max.
    flat = [cell for row in needle.rows for cell in row]
    assert any(RETRIEVAL_NEEDLE_ANSWER in cell for cell in flat)
    amounts = [int(row[1]) for row in needle.rows]
    assert max(amounts) == 24990
    assert max(row[1] for row in needle.rows) == "9990"  # lexical max differs from numeric max


def test_relevancy_decoys_share_schema_and_differ_only_by_annotation():
    warehouse = WarehouseSchemaSynthesizer().generate()
    by_name = {t.name: t for t in warehouse.tables}
    current = by_name[RELEVANCY_NEEDLE_CURRENT]
    stale = by_name[RELEVANCY_NEEDLE_STALE]
    # Identical schema → only the annotation can disambiguate which is live.
    assert current.columns == stale.columns
    assert "canonical" in (current.description or "").lower()
    assert "deprecated" in (stale.description or "").lower()
    assert RELEVANCY_NEEDLE_CURRENT in (stale.description or "")  # stale points at its successor


def test_chain_needle_wires_a_two_hop_join_path():
    warehouse = WarehouseSchemaSynthesizer().generate()
    names = {t.name for t in warehouse.tables}
    assert {REL_NEEDLE_SOURCE, REL_NEEDLE_TARGET, CHAIN_NEEDLE_HOP3}.issubset(names)
    edges = {(j.source_table, j.joining_table) for j in warehouse.joins}
    assert (REL_NEEDLE_SOURCE, REL_NEEDLE_TARGET) in edges
    assert (REL_NEEDLE_TARGET, CHAIN_NEEDLE_HOP3) in edges


def test_needles_map_covers_all_kinds():
    warehouse = WarehouseSchemaSynthesizer().generate()
    assert set(warehouse.needles) == {
        "description",
        "column_type",
        "relationship",
        "view",
        "retrieval",
        "relevancy",
        "chain",
    }
