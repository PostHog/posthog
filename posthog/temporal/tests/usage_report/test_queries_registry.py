"""Static validity checks for the QuerySpec registry.

These run cheaply and catch the kind of refactoring mistakes that would
otherwise only surface during an aggregation activity in production:
duplicated names, multi specs without mappings, two specs writing to the
same destination key, etc.
"""

from posthog.temporal.usage_report.queries import QUERIES, QUERY_INDEX


def test_query_index_matches_queries_list() -> None:
    assert len(QUERY_INDEX) == len(QUERIES)
    for spec in QUERIES:
        assert QUERY_INDEX[spec.name] is spec


def test_query_names_are_unique() -> None:
    names = [spec.name for spec in QUERIES]
    duplicates = {name for name in names if names.count(name) > 1}
    assert not duplicates, f"Duplicate spec names: {duplicates}"


def test_multi_specs_have_non_empty_mapping() -> None:
    for spec in QUERIES:
        if spec.output == "multi":
            assert spec.multi_keys_mapping, f"Multi spec {spec.name!r} has no multi_keys_mapping"


def test_single_specs_have_no_mapping() -> None:
    for spec in QUERIES:
        if spec.output == "single":
            assert not spec.multi_keys_mapping, (
                f"Single spec {spec.name!r} has a multi_keys_mapping; either remove it or change output to 'multi'"
            )


def test_destination_keys_are_unique_across_registry() -> None:
    """Each destination key in `all_data` must be produced by exactly one
    spec — otherwise the aggregator overwrites a real result with another
    one and we silently lose a metric.
    """
    destinations: dict[str, str] = {}
    for spec in QUERIES:
        keys = list(spec.multi_keys_mapping.values()) if spec.output == "multi" else [spec.name]
        for key in keys:
            assert key not in destinations, (
                f"Destination key {key!r} produced by both {destinations[key]!r} and {spec.name!r}"
            )
            destinations[key] = spec.name


def test_kind_is_period_or_snapshot() -> None:
    for spec in QUERIES:
        assert spec.kind in {"period", "snapshot"}, f"Spec {spec.name!r} has unexpected kind {spec.kind!r}"


def test_snapshot_quarantine_disclaimer_lives_in_module() -> None:
    """The whole `kind="snapshot"` mechanism only makes sense alongside the
    explanatory disclaimer at the top of the module. If anyone strips the
    docstring this guard tells them why it matters.
    """
    import posthog.temporal.usage_report.queries as queries_module

    assert queries_module.__doc__ is not None
    assert "snapshot" in queries_module.__doc__.lower()
    assert "re-run safe" in queries_module.__doc__.lower()


def test_period_specs_outnumber_snapshot_specs() -> None:
    """Sanity check: most of the report is event-driven and period-based.
    If this flips, something has gone wrong with the registry.
    """
    period_count = sum(1 for spec in QUERIES if spec.kind == "period")
    snapshot_count = sum(1 for spec in QUERIES if spec.kind == "snapshot")
    assert period_count > snapshot_count, f"Period={period_count} Snapshot={snapshot_count}"
