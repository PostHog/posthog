import pytest

from posthog.test.events_schema_prune import RecordedTest, build_manifest, merge_records, select_prunable

SAFE: RecordedTest = {"hits": {}, "outcome": "passed", "seconds": 1.0}
RECORDING: dict[str, RecordedTest] = {
    "a.py::TestSafe::test_one": SAFE,
    "a.py::TestSafe::test_two": SAFE,
    "a.py::TestMixed::test_reads": {"hits": {"call": 2}, "outcome": "passed", "seconds": 1.0},
    "a.py::TestMixed::test_slow": SAFE,
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
    manifest = build_manifest(RECORDING, DIGESTS.get)

    assert select_prunable(manifest, RECORDING, DIGESTS.get) == PRUNED
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
    manifest = build_manifest(RECORDING, DIGESTS.get)

    assert select_prunable(manifest, collected, digests.get) == expected


def test_merging_recordings_keeps_any_hit_or_failure() -> None:
    merged = merge_records({**SAFE, "hits": {"call": 1}, "outcome": "failed"}, SAFE)

    assert merged["hits"] == {"call": 1}
    assert merged["outcome"] == "failed"
