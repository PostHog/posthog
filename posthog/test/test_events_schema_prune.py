import pytest

from posthog.test.events_schema_prune import build_manifest, listed_tests_that_hit, select_prunable

RECORDING = {
    "a.py::TestSafe::test_one": {"hits": {}, "outcome": "passed", "seconds": 1.0},
    "a.py::TestSafe::test_two": {"hits": {}, "outcome": "skipped", "seconds": 0.0},
    "a.py::TestMixed::test_reads": {"hits": {"call": 2}, "outcome": "passed", "seconds": 1.0},
    "a.py::TestMixed::test_slow": {"hits": {}, "outcome": "passed", "seconds": 1.0},
    "a.py::TestMixed::test_fast": {"hits": {}, "outcome": "passed", "seconds": 0.01},
    "a.py::TestClassSetupReads::test_one": {"hits": {"setup": 1}, "outcome": "passed", "seconds": 1.0},
    "a.py::TestClassSetupReads::test_two": {"hits": {}, "outcome": "passed", "seconds": 1.0},
    "a.py::TestFlaky::test_one": {"hits": {}, "outcome": "failed", "seconds": 1.0},
    "b.py::test_one": {"hits": {}, "outcome": "passed", "seconds": 1.0},
    "b.py::test_two[param]": {"hits": {}, "outcome": "passed", "seconds": 1.0},
    "c.py::test_module_fixture_reads": {"hits": {"setup": 1}, "outcome": "passed", "seconds": 1.0},
    "c.py::test_other": {"hits": {}, "outcome": "passed", "seconds": 1.0},
}
DIGESTS = {"a.py": "a1", "b.py": "b1", "c.py": "c1"}
PRUNED = {
    "a.py::TestSafe::test_one",
    "a.py::TestSafe::test_two",
    "a.py::TestMixed::test_slow",
    "b.py::test_one",
    "b.py::test_two[param]",
}


def test_prunes_only_tests_the_recording_proved_independent() -> None:
    manifest = build_manifest(RECORDING, DIGESTS.get, min_seconds=0.1)

    assert select_prunable(manifest, RECORDING, DIGESTS.get) == PRUNED
    assert listed_tests_that_hit(manifest, RECORDING, DIGESTS.get) == []


@pytest.mark.parametrize(
    ("collected", "digests", "expected"),
    [
        (["b.py::test_one", "b.py::test_two[param]"], {"b.py": "b2"}, set()),
        (["b.py::test_one", "b.py::test_two[param]", "b.py::test_two[new]"], DIGESTS, set()),
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
    later = {**RECORDING, "b.py::test_one": {"hits": {"call": 1}, "outcome": "passed", "seconds": 1.0}}

    assert listed_tests_that_hit(manifest, later, DIGESTS.get) == ["b.py::test_one"]
    assert listed_tests_that_hit(manifest, later, {**DIGESTS, "b.py": "b2"}.get) == []
