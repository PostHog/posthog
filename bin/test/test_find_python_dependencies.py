#!/usr/bin/env python3
"""
Tests for find_python_dependencies.py
"""

import unittest

from parameterized import parameterized

from bin.find_python_dependencies import (
    LOCAL_PACKAGES,
    REPO_ROOT,
    build_import_graph,
    check_if_changes_affect_entrypoint,
    find_all_dependency_files,
    module_to_file,
)


class TestFindPythonDependencies(unittest.TestCase):
    graph = None

    @classmethod
    def setUpClass(cls):
        cls.graph = build_import_graph(LOCAL_PACKAGES)

    @parameterized.expand(
        [
            ("simple_module", "posthog.utils", "posthog/utils.py"),
            ("package_module", "posthog.temporal.subscriptions", "posthog/temporal/subscriptions/__init__.py"),
            ("nested_module", "posthog.hogql_queries.query_runner", "posthog/hogql_queries/query_runner.py"),
            ("nonexistent_module", "posthog.nonexistent.module", None),
            ("ee_module", "ee.tasks.subscriptions.subscription_utils", "ee/tasks/subscriptions/subscription_utils.py"),
        ]
    )
    def test_module_to_file(self, _name, module, expected_file):
        assert module_to_file(module) == expected_file

    def test_returns_only_python_file_paths(self):
        files = find_all_dependency_files(self.graph, "posthog.temporal.subscriptions")
        assert isinstance(files, set)
        for f in files:
            assert f.endswith(".py"), f"Expected .py file, got {f}"

    @parameterized.expand(
        [
            # Dependencies - should be included
            ("The utils file (e.g. caching key)", "posthog/utils.py", True),
            ("The underlying query runner", "posthog/hogql_queries/query_runner.py", True),
            # Non-dependencies - should NOT be included
            ("API endpoint that calls the worker", "ee/api/subscription.py", False),
            ("Schedule config that starts workflows", "posthog/temporal/schedule.py", False),
            ("Unrelated admin module", "posthog/admin/__init__.py", False),
        ]
    )
    def test_file_inclusion(self, _name, file_path, should_be_included):
        files = find_all_dependency_files(self.graph, "posthog.temporal.subscriptions")
        if should_be_included:
            assert file_path in files
        else:
            assert file_path not in files

    @parameterized.expand(
        [
            # Direct dependencies - should trigger rebuild
            ("entrypoint_init", "posthog/temporal/subscriptions/__init__.py", True),
            ("entrypoint_workflow", "posthog/temporal/subscriptions/subscription_scheduling_workflow.py", True),
            # Transitive dependencies (the bug that caused issue https://github.com/PostHog/posthog/pull/42307) - should trigger rebuild
            ("transitive_utils", "posthog/utils.py", True),
            ("transitive_query_runner", "posthog/hogql_queries/query_runner.py", True),
            # Export-related files - should trigger rebuild
            ("exporter", "posthog/tasks/exporter.py", True),
            ("image_exporter", "posthog/tasks/exports/image_exporter.py", True),
            ("subscription_utils", "ee/tasks/subscriptions/subscription_utils.py", True),
            # Files that should NOT affect the worker
            ("api_endpoint", "ee/api/subscription.py", False),
            ("schedule_config", "posthog/temporal/schedule.py", False),
            ("frontend_code", "frontend/src/test.tsx", False),
            ("rust_code", "rust/some_file.rs", False),
            ("non_python", "pyproject.toml", False),
        ]
    )
    def test_change_detection(self, _name, changed_file, should_be_affected):
        affected, _matching = check_if_changes_affect_entrypoint(
            self.graph,
            "posthog.temporal.subscriptions",
            [changed_file],
        )
        assert affected == should_be_affected, (
            f"Expected {changed_file} to {'affect' if should_be_affected else 'NOT affect'} "
            f"the worker, but got affected={affected}"
        )

    def test_multiple_changes_one_affects(self):
        affected, matching = check_if_changes_affect_entrypoint(
            self.graph,
            "posthog.temporal.subscriptions",
            ["frontend/test.tsx", "posthog/utils.py", "README.md"],
        )
        assert affected
        assert matching == ["posthog/utils.py"]

    def test_multiple_changes_none_affect(self):
        affected, matching = check_if_changes_affect_entrypoint(
            self.graph,
            "posthog.temporal.subscriptions",
            ["frontend/test.tsx", "README.md", "rust/main.rs"],
        )
        assert not affected
        assert matching == []

    def test_returns_sorted_matching_files(self):
        _affected, matching = check_if_changes_affect_entrypoint(
            self.graph,
            "posthog.temporal.subscriptions",
            ["posthog/utils.py", "posthog/hogql_queries/query_runner.py", "ee/models/license.py"],
        )
        assert len(matching) > 1, "Need multiple matches to verify sorting"
        assert matching == sorted(matching)

    @parameterized.expand(
        [
            # Entrypoint - should trigger rebuild
            ("entrypoint_init", "posthog/temporal/subscriptions/__init__.py", True),
            ("entrypoint_workflow", "posthog/temporal/subscriptions/subscription_scheduling_workflow.py", True),
            # posthog/temporal/common - should trigger rebuild
            ("temporal_common_base", "posthog/temporal/common/base.py", True),
            ("temporal_common_client", "posthog/temporal/common/client.py", True),
            # posthog/tasks/exporter.py - should trigger rebuild
            ("exporter", "posthog/tasks/exporter.py", True),
            # posthog/tasks/exports/ - should trigger rebuild
            ("image_exporter", "posthog/tasks/exports/image_exporter.py", True),
            ("csv_exporter", "posthog/tasks/exports/csv_exporter.py", True),
            # ee/tasks/subscriptions/ - should trigger rebuild
            ("subscription_utils", "ee/tasks/subscriptions/subscription_utils.py", True),
            ("email_subscriptions", "ee/tasks/subscriptions/email_subscriptions.py", True),
            # Transitive dependencies - should trigger rebuild
            ("utils", "posthog/utils.py", True),
            ("query_runner", "posthog/hogql_queries/query_runner.py", True),
            # Non-dependencies - should NOT trigger rebuild
            ("api_endpoint", "ee/api/subscription.py", False),
            ("schedule_config", "posthog/temporal/schedule.py", False),
            ("admin", "posthog/admin/admins/batch_imports.py", False),
            ("tests", "posthog/test/test_utils.py", False),
        ]
    )
    def test_analytics_platform_worker_file_triggers_rebuild(self, _name, changed_file, should_trigger):
        affected, _ = check_if_changes_affect_entrypoint(
            self.graph,
            "posthog.temporal.subscriptions",
            [changed_file],
        )
        if should_trigger:
            assert affected, f"{changed_file} should trigger a rebuild but was not detected"
        else:
            assert not affected, f"{changed_file} should NOT trigger a rebuild but was detected"

    @parameterized.expand(
        [
            ("posthog", "posthog"),
            ("ee", "ee"),
        ]
    )
    def test_graph_contains_package_modules(self, _name, package):
        modules = self.graph.find_children(package)
        assert len(modules) > 0

    @parameterized.expand([(pkg,) for pkg in LOCAL_PACKAGES])
    def test_package_exists(self, pkg):
        pkg_path = REPO_ROOT / pkg
        assert pkg_path.exists(), f"Package {pkg} configured but directory doesn't exist"
        assert (pkg_path / "__init__.py").exists(), f"Package {pkg} missing __init__.py"


if __name__ == "__main__":
    unittest.main()
