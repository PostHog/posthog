import pytest

from posthog.test.events_schema_prune import build_manifest, merge_records, select_prunable, stale_entries

SAFE = {"hits": {}, "outcome": "passed", "seconds": 1.0}
RECORDING = {
    "a.py::TestSafe::test_one": SAFE,
    "a.py::TestSafe::test_two": SAFE,
    "a.py::TestMixed::test_reads": {"hits": {"call": 2}, "outcome": "passed", "seconds": 1.0},
    "a.py::TestMixed::test_slow": SAFE,
    "a.py::TestMixed::test_fast": {"hits": {}, "outcome": "passed", "seconds": 0.01},
    "a.py::TestMixed::test_skipped": {"hits": {}, "outcome": "skipped", "seconds": 1.0},
    "a.py::TestMixed::test_xfail": {"hits": {}, "outcome": "xfail", "seconds": 1.0},
    "a.py::TestClassSetupReads::test_one": {"hits": {"setup:class": 1}, "outcome": "passed", "seconds": 1.0},
    "a.py::TestClassSetupReads::test_two": SAFE,
    "a.py::TestFlaky::test_one": {"hits": {}, "outcome": "failed", "seconds": 1.0},
    "b.py::test_one": SAFE,
    "b.py::test_two[param]": SAFE,
    "c.py::test_function_fixture_reads": {"hits": {"setup:function": 1}, "outcome": "passed", "seconds": 1.0},
    "c.py::test_other": SAFE,
    "d.py::TestFirst::test_one": {"hits": {"setup:module": 1}, "outcome": "passed", "seconds": 1.0},
    "d.py::TestSecond::test_one": SAFE,
    "e.py::TestFirst::test_one": {"hits": {"setup": 1}, "outcome": "passed", "seconds": 1.0},
    "e.py::TestSecond::test_one": SAFE,
}
DIGESTS = {"a.py": "a1", "b.py": "b1", "c.py": "c1", "d.py": "d1", "e.py": "e1"}
PRUNED = {
    "a.py::TestSafe::test_one",
    "a.py::TestSafe::test_two",
    "a.py::TestMixed::test_slow",
    "b.py::test_one",
    "b.py::test_two[param]",
    "c.py::test_other",
}


def test_prunes_only_tests_the_recording_proved_independent() -> None:
    manifest = build_manifest(RECORDING, DIGESTS.get, min_seconds=0.1)

    assert select_prunable(manifest, RECORDING, DIGESTS.get) == PRUNED
    assert stale_entries(manifest, RECORDING, DIGESTS.get) == []
    with pytest.raises(ValueError):
        build_manifest({**RECORDING, "b.py::test_one": {**SAFE, "hits": {"setup:session": 1}}}, DIGESTS.get)


@pytest.mark.parametrize(
    ("collected", "digests", "expected"),
    [
        (["b.py::test_one", "b.py::test_two[param]"], {"b.py": "b2"}, set()),
        (["b.py::test_one", "b.py::test_two[param]", "b.py::test_two[new]"], DIGESTS, set()),
        (["b.py::test_one", "b.py::test_two[replaced]"], DIGESTS, set()),
        (["a.py::TestSafe::test_one", "a.py::TestSafe::test_two", "a.py::TestSafe::test_new"], DIGESTS, set()),
        (["a.py::TestMixed::test_slow", "a.py::TestMixed::test_new"], DIGESTS, {"a.py::TestMixed::test_slow"}),
    ],
)
def test_runs_tests_the_recording_did_not_see(
    collected: list[str], digests: dict[str, str], expected: set[str]
) -> None:
    manifest = build_manifest(RECORDING, DIGESTS.get, min_seconds=0.1)

    assert select_prunable(manifest, collected, digests.get) == expected


def test_check_flags_a_listed_test_that_now_reads_the_json_tables() -> None:
    manifest = build_manifest(RECORDING, DIGESTS.get, min_seconds=0.1)
    later = {**RECORDING, "b.py::test_one": {**SAFE, "hits": {"call": 1}}}

    assert stale_entries(manifest, later, DIGESTS.get) == ["b.py::test_one"]
    assert stale_entries(manifest, {"b.py::test_one": later["b.py::test_one"]}, DIGESTS.get) == ["b.py::test_one"]
    assert stale_entries(manifest, later, {**DIGESTS, "b.py": "b2"}.get) == []


def test_merging_recordings_keeps_any_hit_or_failure() -> None:
    merged = merge_records({**SAFE, "hits": {"call": 1}, "outcome": "failed"}, SAFE)

    assert merged["hits"] == {"call": 1}
    assert merged["outcome"] == "failed"
