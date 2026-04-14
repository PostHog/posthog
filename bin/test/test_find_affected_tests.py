#!/usr/bin/env python3
import os
import json
import tempfile
import textwrap
import subprocess
from pathlib import Path

import unittest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from bin.find_affected_tests import (
    FULL_RUN_PATTERNS,
    LOCAL_PACKAGES,
    REPO_ROOT,
    _ast_get_imports,
    _build_ast_reverse_map,
    build_reverse_map,
    changed_files_from_git,
    estimate_duration,
    is_test_module,
    load_durations,
    module_to_file,
    pattern_is_covered,
    requires_full_run,
)


class TestIsTestModule(unittest.TestCase):
    @parameterized.expand(
        [
            ("test_file", "posthog.api.test.test_user", "posthog/api/test/test_user.py", True),
            ("eval_file", "posthog.eval.eval_query", "posthog/eval/eval_query.py", True),
            ("nested_test", "ee.api.test.test_billing", "ee/api/test/test_billing.py", True),
            ("source_file", "posthog.models.team", "posthog/models/team.py", False),
            ("conftest", "posthog.conftest", "posthog/conftest.py", False),
            ("none_path", "posthog.missing", None, False),
            ("test_prefix_in_subdir", "posthog.utils.test_helpers", "posthog/utils/test_helpers.py", True),
        ]
    )
    def test_classification(self, _name, module, file_path, expected):
        self.assertEqual(is_test_module(module, file_path), expected)


class TestModuleToFile(unittest.TestCase):
    @parameterized.expand(
        [
            ("simple_module", "posthog.utils", "posthog/utils.py"),
            ("package_init", "posthog.models", "posthog/models/__init__.py"),
            ("nested_module", "posthog.api.user", "posthog/api/user.py"),
            ("nonexistent", "posthog.does.not.exist", None),
            ("ee_module", "ee.models.license", "ee/models/license.py"),
        ]
    )
    def test_resolution(self, _name, module, expected):
        self.assertEqual(module_to_file(module), expected)


class TestRequiresFullRun(unittest.TestCase):
    @parameterized.expand(
        [
            ("conftest", "posthog/api/conftest.py", True),
            ("settings", "posthog/settings/web.py", True),
            ("test_infra", "posthog/test/base.py", True),
            ("manage_py", "manage.py", True),
            ("pyproject", "pyproject.toml", True),
            ("uv_lock", "uv.lock", True),
            ("ci_backend", ".github/workflows/ci-backend.yml", True),
            ("docker_compose", "docker-compose.dev.yml", True),
            ("docker_ch", "docker/clickhouse/config.xml", True),
            ("schema_json_not_full", "frontend/src/queries/schema.json", False),
            ("email_templates", "frontend/public/email/template.html", True),
            ("rust_property_models", "rust/feature-flags/src/properties/property_models.rs", True),
            ("plugin_transpiler", "common/plugin_transpiler/src/index.ts", True),
            ("requirements", "requirements.txt", True),
            ("requirements_dev", "requirements-dev.txt", True),
            ("normal_source", "posthog/models/team.py", False),
            ("normal_test", "posthog/api/test/test_user.py", False),
            ("migration", "posthog/migrations/0500_something.py", False),
            ("frontend_ts", "frontend/src/scenes/insights/Insight.tsx", False),
            ("ee_source", "ee/api/hooks.py", False),
        ]
    )
    def test_pattern_matching(self, _name, changed_file, expected):
        self.assertEqual(requires_full_run(changed_file), expected, f"Failed for {changed_file}")


class TestPatternIsCovered(unittest.TestCase):
    @parameterized.expand(
        [
            ("posthog_glob", "posthog/**", True),
            ("ee_glob", "ee/**", True),
            ("products_glob", "products/**", True),
            ("common_glob", "common/**", True),
            ("conftest", "conftest.py", True),
            ("docker_compose", "docker-compose*", True),
            ("gate_only_bin", "bin/build-schema-latest-versions.py", True),
            ("random_uncovered", "some/random/path", False),
        ]
    )
    def test_coverage(self, _name, pattern, expected):
        self.assertEqual(pattern_is_covered(pattern), expected, f"Failed for {pattern}")


class TestAstGetImports(unittest.TestCase):
    def _write_temp(self, code, filename="test_mod.py", subdir=""):
        path = os.path.join(self.tmpdir, subdir, filename) if subdir else os.path.join(self.tmpdir, filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(textwrap.dedent(code))
        # Return path relative to tmpdir so dirname-based module resolution works
        return os.path.relpath(path, self.tmpdir)

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_cwd = os.getcwd()
        os.chdir(self.tmpdir)

    def tearDown(self):
        os.chdir(self._orig_cwd)

    @parameterized.expand(
        [
            (
                "absolute_import",
                "import posthog.models.team",
                {"posthog.models.team"},
            ),
            (
                "from_import",
                "from posthog.models import Team",
                {"posthog.models"},
            ),
            (
                "multiple_imports",
                "import os\nimport posthog.utils\nfrom ee.models import License",
                {"os", "posthog.utils", "ee.models"},
            ),
        ]
    )
    def test_absolute_imports(self, _name, code, expected):
        path = self._write_temp(code)
        self.assertEqual(_ast_get_imports(path), expected)

    def test_relative_import_with_module(self):
        path = self._write_temp("from .utils import helper", subdir="pkg/sub")
        result = _ast_get_imports(path)
        self.assertIn("pkg.sub.utils", result)

    def test_relative_import_parent(self):
        path = self._write_temp("from ..models import Foo", subdir="pkg/sub")
        result = _ast_get_imports(path)
        self.assertIn("pkg.models", result)

    def test_relative_import_names_only(self):
        # from . import foo — no module, just names
        path = self._write_temp("from . import foo, bar", subdir="pkg/sub")
        result = _ast_get_imports(path)
        self.assertIn("pkg.sub.foo", result)
        self.assertIn("pkg.sub.bar", result)

    def test_syntax_error_returns_empty(self):
        path = self._write_temp("def broken(:\n    pass")
        self.assertEqual(_ast_get_imports(path), set())

    def test_nonexistent_file_returns_empty(self):
        self.assertEqual(_ast_get_imports("/nonexistent/file.py"), set())

    def test_empty_file(self):
        path = self._write_temp("")
        self.assertEqual(_ast_get_imports(path), set())


class TestEstimateDuration(unittest.TestCase):
    def test_sums_matching_test_durations(self):
        durations = {
            "posthog/api/test/test_user.py::TestUser::test_create": 1.0,
            "posthog/api/test/test_user.py::TestUser::test_update": 2.0,
            "posthog/api/test/test_team.py::TestTeam::test_list": 3.0,
        }
        result = estimate_duration(["posthog/api/test/test_user.py"], durations)
        self.assertAlmostEqual(result, 3.0)

    def test_no_matching_tests(self):
        durations = {
            "posthog/api/test/test_user.py::TestUser::test_create": 1.0,
        }
        result = estimate_duration(["posthog/api/test/test_team.py"], durations)
        self.assertAlmostEqual(result, 0.0)

    def test_empty_durations(self):
        self.assertAlmostEqual(estimate_duration(["posthog/api/test/test_user.py"], {}), 0.0)

    def test_empty_test_list(self):
        durations = {"posthog/api/test/test_user.py::TestUser::test_create": 1.0}
        self.assertAlmostEqual(estimate_duration([], durations), 0.0)

    def test_multiple_test_files(self):
        durations = {
            "a/test_x.py::T::t1": 1.5,
            "a/test_x.py::T::t2": 2.5,
            "b/test_y.py::T::t1": 3.0,
            "c/test_z.py::T::t1": 4.0,
        }
        result = estimate_duration(["a/test_x.py", "b/test_y.py"], durations)
        self.assertAlmostEqual(result, 7.0)


class TestLoadDurations(unittest.TestCase):
    def test_loads_valid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"test.py::T::t": 1.5}, f)
            f.flush()
            with patch("bin.find_affected_tests.DURATIONS_PATH", Path(f.name)):
                result = load_durations()
                self.assertEqual(result, {"test.py::T::t": 1.5})
        os.unlink(f.name)

    def test_missing_file_returns_empty(self):
        with patch("bin.find_affected_tests.DURATIONS_PATH", Path("/nonexistent/file.json")):
            self.assertEqual(load_durations(), {})

    def test_invalid_json_returns_empty(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not json{{{")
            f.flush()
            with patch("bin.find_affected_tests.DURATIONS_PATH", Path(f.name)):
                self.assertEqual(load_durations(), {})
        os.unlink(f.name)


class TestBuildReverseMap(unittest.TestCase):
    """Integration tests using the real codebase."""

    reverse_map = {}
    total_test_count = 0
    all_known_source = set()

    @classmethod
    def setUpClass(cls):
        os.chdir(REPO_ROOT)
        cls.reverse_map, cls.total_test_count, cls.all_known_source = build_reverse_map()

    def test_returns_nonempty_map(self):
        self.assertGreater(len(self.reverse_map), 0)

    def test_total_test_count_includes_ast_tests(self):
        # AST fallback discovers ~505 extra test files beyond grimp's ~1115
        self.assertGreater(self.total_test_count, 1115)

    def test_reverse_map_values_are_sorted_lists(self):
        for source, tests in list(self.reverse_map.items())[:20]:
            self.assertIsInstance(tests, list, f"Value for {source} should be a list")
            self.assertEqual(tests, sorted(tests), f"Tests for {source} should be sorted")

    def test_all_known_source_is_superset_of_mapped(self):
        mapped_sources = set(self.reverse_map.keys())
        self.assertTrue(mapped_sources.issubset(self.all_known_source))

    def test_all_known_source_includes_unmapped_files(self):
        # Files like migrations, apps.py are known but have no test deps
        self.assertGreater(len(self.all_known_source), len(self.reverse_map))

    @parameterized.expand(
        [
            # Core files that many tests depend on (via grimp re-exports)
            ("team_model", "posthog/models/team/team.py"),
            ("schema", "posthog/schema.py"),
            ("redis", "posthog/redis.py"),
        ]
    )
    def test_high_fanout_files_are_mapped(self, _name, source_file):
        self.assertIn(source_file, self.reverse_map, f"{source_file} should be in reverse map")
        self.assertGreater(len(self.reverse_map[source_file]), 100, f"{source_file} should have many dependents")

    @parameterized.expand(
        [
            # Files in dirs without __init__.py — only discoverable via AST fallback
            ("billing", "ee/billing/quota_limiting.py"),
            ("hogql", "posthog/hogql/query.py"),
        ]
    )
    def test_ast_fallback_maps_grimp_invisible_files(self, _name, source_file):
        if os.path.isfile(source_file):
            self.assertIn(
                source_file,
                self.reverse_map,
                f"{source_file} should be mapped via AST fallback",
            )

    @parameterized.expand(
        [
            # Test files in dirs without __init__.py — AST should discover them
            ("billing_tests", "ee/billing/test/test_quota_limiting.py"),
            ("hogql_tests", "posthog/hogql/test/test_metadata.py"),
        ]
    )
    def test_ast_test_files_appear_in_reverse_map_values(self, _name, test_file):
        if not os.path.isfile(test_file):
            self.skipTest(f"{test_file} does not exist on disk")
        all_tests = set()
        for tests in self.reverse_map.values():
            all_tests.update(tests)
        self.assertIn(test_file, all_tests, f"AST-discovered test {test_file} should appear as a dependent")

    @parameterized.expand(
        [
            ("migration", "posthog/migrations/0001_initial.py"),
            ("apps_py", "posthog/apps.py"),
        ]
    )
    def test_no_dep_files_in_all_known_but_not_reverse_map(self, _name, source_file):
        self.assertIn(source_file, self.all_known_source, f"{source_file} should be known")
        self.assertNotIn(source_file, self.reverse_map, f"{source_file} should have no test deps")


class TestBuildAstReverseMap(unittest.TestCase):
    """Unit tests for the AST fallback with a synthetic file tree."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write(self, relpath, code=""):
        path = os.path.join(self.tmpdir, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(textwrap.dedent(code))
        return path

    def test_empty_when_grimp_covers_everything(self):
        self._write("pkg/source.py", "x = 1")
        grimp_files = {os.path.join(self.tmpdir, "pkg/source.py")}
        # Patch LOCAL_PACKAGES to point at nothing so os.walk finds nothing
        with patch("bin.find_affected_tests.LOCAL_PACKAGES", ()):
            reverse_map, ast_tests, ast_sources = _build_ast_reverse_map(grimp_files, set())
        self.assertEqual(len(reverse_map), 0)
        self.assertEqual(len(ast_tests), 0)
        self.assertEqual(len(ast_sources), 0)

    def test_discovers_files_grimp_missed(self):
        # Create a mini package structure without __init__.py
        self._write("testpkg/lib/helpers.py", "def helper(): pass")
        self._write("testpkg/lib/test_helpers.py", "from testpkg.lib.helpers import helper")
        self._write("testpkg/__init__.py", "")

        grimp_files: set[str] = set()  # grimp sees nothing
        with patch("bin.find_affected_tests.LOCAL_PACKAGES", ("testpkg",)):
            os.chdir(self.tmpdir)
            reverse_map, ast_tests, ast_sources = _build_ast_reverse_map(grimp_files, set())

        self.assertIn("testpkg/lib/test_helpers.py", ast_tests)
        self.assertIn("testpkg/lib/helpers.py", ast_sources)
        self.assertIn("testpkg/lib/helpers.py", reverse_map)
        self.assertIn("testpkg/lib/test_helpers.py", reverse_map["testpkg/lib/helpers.py"])

    def test_grimp_test_importing_ast_only_source_is_captured(self):
        # grimp-visible test (has __init__.py) importing an AST-only source
        # (directory missing __init__.py). Without seeding BFS from grimp
        # tests, this edge would be invisible.
        self._write("testpkg/__init__.py", "")
        self._write("testpkg/api/__init__.py", "")
        self._write("testpkg/api/test_query.py", "from testpkg.hogql.query import run")
        # hogql dir has no __init__.py → grimp can't see it
        self._write("testpkg/hogql/query.py", "def run(): pass")

        grimp_test_file = "testpkg/api/test_query.py"
        # Simulate grimp having discovered the test file but not the AST source
        grimp_files = {grimp_test_file, "testpkg/__init__.py", "testpkg/api/__init__.py"}
        grimp_test_files = {grimp_test_file}

        with patch("bin.find_affected_tests.LOCAL_PACKAGES", ("testpkg",)):
            os.chdir(self.tmpdir)
            reverse_map, ast_tests, ast_sources = _build_ast_reverse_map(grimp_files, grimp_test_files)

        self.assertIn("testpkg/hogql/query.py", ast_sources)
        self.assertNotIn(grimp_test_file, ast_tests)  # grimp test isn't an AST-only test
        self.assertIn("testpkg/hogql/query.py", reverse_map)
        self.assertIn(grimp_test_file, reverse_map["testpkg/hogql/query.py"])

    def tearDown(self):
        os.chdir(REPO_ROOT)


class TestFullRunPatternsCompleteness(unittest.TestCase):
    def test_all_patterns_are_strings(self):
        for pattern in FULL_RUN_PATTERNS:
            self.assertIsInstance(pattern, str)

    def test_conftest_triggers_full_run(self):
        self.assertTrue(requires_full_run("posthog/api/conftest.py"))
        self.assertTrue(requires_full_run("ee/conftest.py"))
        self.assertTrue(requires_full_run("conftest.py"))

    def test_nested_settings_triggers_full_run(self):
        self.assertTrue(requires_full_run("posthog/settings/web.py"))
        self.assertTrue(requires_full_run("posthog/settings/__init__.py"))

    def test_docker_compose_variants_trigger_full_run(self):
        self.assertTrue(requires_full_run("docker-compose.yml"))
        self.assertTrue(requires_full_run("docker-compose.dev.yml"))
        self.assertTrue(requires_full_run("docker-compose.base.yml"))


class TestChangedFilesFromGit(unittest.TestCase):
    @patch("bin.find_affected_tests.subprocess.run")
    def test_passes_triple_dot_range_to_git(self, mock_run):
        # `...` is the load-bearing detail — it resolves against the merge-base
        # so files pulled in via a merge of base_ref into the branch are excluded.
        mock_run.return_value = MagicMock(stdout="")
        changed_files_from_git("origin/master")
        args = mock_run.call_args.args[0]
        self.assertEqual(args, ["git", "diff", "--name-only", "origin/master...HEAD"])

    @parameterized.expand(
        [
            (
                "normal_lines",
                "posthog/api/user.py\nposthog/models/team.py\n",
                ["posthog/api/user.py", "posthog/models/team.py"],
            ),
            ("drops_blank_lines", "a.py\n\n  \nb.py\n", ["a.py", "b.py"]),
            ("empty_diff", "", []),
        ]
    )
    @patch("bin.find_affected_tests.subprocess.run")
    def test_parses_stdout(self, _name, stdout, expected, mock_run):
        mock_run.return_value = MagicMock(stdout=stdout)
        self.assertEqual(changed_files_from_git("origin/master"), expected)

    @patch("bin.find_affected_tests.subprocess.run")
    def test_propagates_git_failure(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=128, cmd=["git", "diff"], stderr="fatal: bad revision"
        )
        with self.assertRaises(subprocess.CalledProcessError):
            changed_files_from_git("does/not/exist")


class TestLocalPackagesExist(unittest.TestCase):
    @parameterized.expand([(pkg,) for pkg in LOCAL_PACKAGES])
    def test_package_directory_exists(self, pkg):
        self.assertTrue(
            os.path.isdir(os.path.join(REPO_ROOT, pkg)),
            f"LOCAL_PACKAGES entry '{pkg}' directory does not exist",
        )


if __name__ == "__main__":
    unittest.main()
