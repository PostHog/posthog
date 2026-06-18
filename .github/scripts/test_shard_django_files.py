"""Tests for file-level Django shard planning.

Run with: uv run --with pytest pytest .github/scripts/test_shard_django_files.py
"""

import json

import pytest

from shard_django_files import (
    SEGMENTS,
    build_plan,
    discover_files,
    is_test_file,
    legacy_args,
    load_file_weights,
    weighted_files,
)


def _plan_files(plan):
    whole = [f for s in plan if s.split_total is None for f in s.files]
    split = sorted({s.files[0] for s in plan if s.split_total is not None})
    return whole, split


class TestIsTestFile:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("test_foo.py", True),
            ("foo_test.py", True),
            ("conftest.py", False),
            ("foo.py", False),
            ("test_foo.txt", False),
            ("testfoo.py", False),
        ],
    )
    def test_matches_pytest_patterns(self, name, expected):
        assert is_test_file(name) is expected


class TestBuildPlanCoverage:
    @pytest.mark.parametrize("shards", [2, 3, 7, 38])
    def test_every_file_assigned_exactly_once(self, shards):
        files = [(f"posthog/test/test_{i}.py", float(i % 5 + 1)) for i in range(200)]
        plan = build_plan(files, shards)
        whole, split = _plan_files(plan)
        assert len(plan) == shards
        # whole-file shards partition the universe minus any split files
        assert sorted(whole) == sorted(f for f, _ in files if f not in split)
        assert len(whole) == len(set(whole))  # no duplicates

    @pytest.mark.parametrize("shards", [1, 2, 5, 10, 50])
    def test_plan_length_equals_shards_when_files_outnumber_shards(self, shards):
        files = [(f"t_{i}.py", float(i % 7 + 1)) for i in range(100)]
        assert len(build_plan(files, shards)) == shards

    @pytest.mark.parametrize("shards", [2, 11, 20])
    def test_plan_never_exceeds_shards_even_with_many_oversized(self, shards):
        # Pathological: every file heavier than ideal. Must never overflow
        # (overflow groups would never be requested -> silently dropped tests).
        files = [(f"t_{i}.py", 1.0) for i in range(10)]
        plan = build_plan(files, shards)
        assert len(plan) == shards
        whole, split = _plan_files(plan)
        assert sorted(whole + split) == sorted(f for f, _ in files)


class TestBuildPlanSplitting:
    def test_oversized_file_gets_dedicated_split_shards(self):
        # one heavy file (heavier than ideal) + lots of filler so a whole bin remains
        files = [("posthog/test/test_huge.py", 100.0)] + [(f"t_{i}.py", 10.0) for i in range(50)]
        plan = build_plan(files, 10)
        split_shards = [s for s in plan if s.split_total is not None]
        assert len(split_shards) >= 2
        assert all(s.files == ["posthog/test/test_huge.py"] for s in split_shards)
        groups = sorted(s.split_group for s in split_shards)
        assert groups == list(range(1, len(split_shards) + 1))

    def test_split_shard_pytest_args(self):
        files = [("test_huge.py", 100.0)] + [(f"f{i}.py", 10.0) for i in range(20)]
        plan = build_plan(files, 4)
        split = next(s for s in plan if s.split_total is not None)
        assert split.pytest_args() == f"test_huge.py --splits {split.split_total} --group {split.split_group}"

    def test_no_split_when_files_fit(self):
        files = [(f"t_{i}.py", 10.0) for i in range(8)]
        plan = build_plan(files, 4)
        assert all(s.split_total is None for s in plan)


class TestBuildPlanDeterminism:
    def test_identical_input_yields_identical_plan(self):
        files = [(f"posthog/test/test_{i}.py", float((i * 7) % 13)) for i in range(150)]
        a = [(s.files, s.split_total, s.split_group) for s in build_plan(files, 9)]
        b = [(s.files, s.split_total, s.split_group) for s in build_plan(list(files), 9)]
        assert a == b


class TestBalance:
    @pytest.mark.parametrize("shards", [5, 12, 38])
    def test_imbalance_stays_bounded(self, shards):
        # realistic-ish: many small, a few large
        files = [(f"t_{i}.py", 1.0) for i in range(500)]
        files += [(f"big_{i}.py", 50.0) for i in range(10)]
        plan = build_plan(files, shards)
        total = sum(w for _, w in files)
        ideal = total / shards
        worst = max(s.weight for s in plan)
        assert worst <= ideal * 1.35


class TestWeights:
    def test_untimed_files_get_median_weight(self):
        weights = {"a.py": 10.0, "b.py": 20.0, "c.py": 30.0}
        result = dict(weighted_files(["a.py", "b.py", "c.py", "new.py"], weights))
        assert result["new.py"] == 20.0  # median of [10,20,30]

    def test_no_timed_files_defaults_to_one(self):
        result = dict(weighted_files(["new.py"], {}))
        assert result["new.py"] == 1.0

    def test_load_file_weights_sums_per_file(self, tmp_path):
        p = tmp_path / ".test_durations"
        p.write_text(json.dumps({"a.py::test_x": 1.5, "a.py::test_y": 2.5, "b.py::test_z": 4.0}))
        assert load_file_weights(str(p)) == {"a.py": 4.0, "b.py": 4.0}

    @pytest.mark.parametrize("bad", [{"a.py::t": "nan"}, {"a.py::t": float("inf")}, {"a.py::t": -1.0}])
    def test_load_file_weights_skips_invalid(self, tmp_path, bad):
        p = tmp_path / ".test_durations"
        p.write_text(json.dumps(bad))
        assert load_file_weights(str(p)) == {}

    def test_load_file_weights_missing_file(self):
        assert load_file_weights("/nonexistent/.test_durations") == {}


class TestDiscoverFiles:
    def test_finds_test_files_and_respects_excludes(self, tmp_path):
        (tmp_path / "posthog/api/test").mkdir(parents=True)
        (tmp_path / "posthog/temporal/test").mkdir(parents=True)
        (tmp_path / "posthog/user_scripts").mkdir(parents=True)
        (tmp_path / "posthog/api/test/test_a.py").write_text("")
        (tmp_path / "posthog/api/test/b_test.py").write_text("")
        (tmp_path / "posthog/api/test/conftest.py").write_text("")  # not a test file
        (tmp_path / "posthog/temporal/test/test_t.py").write_text("")  # excluded segment dir
        (tmp_path / "posthog/user_scripts/test_u.py").write_text("")  # global ignore
        (tmp_path / "ee").mkdir()
        found = discover_files("Core", str(tmp_path))
        assert found == ["posthog/api/test/b_test.py", "posthog/api/test/test_a.py"]

    def test_explicit_file_in_include(self, tmp_path):
        d = tmp_path / "posthog/api/test/dashboards"
        d.mkdir(parents=True)
        (d / "test_dashboard.py").write_text("")
        found = discover_files("CorePOE", str(tmp_path))
        assert "posthog/api/test/dashboards/test_dashboard.py" in found


class TestLegacyArgs:
    @pytest.mark.parametrize("segment", sorted(SEGMENTS))
    def test_legacy_args_include_splits_and_group(self, segment):
        out = legacy_args(segment, 7, 3)
        assert "--splits 7 --group 3" in out
        assert all(token in out for token in SEGMENTS[segment]["legacy"])
