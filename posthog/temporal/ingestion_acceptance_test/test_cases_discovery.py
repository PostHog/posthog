"""Test discovery for acceptance tests."""

import inspect
import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runner import AcceptanceTest


@dataclass
class TestCase:
    """A discovered test case."""

    module_name: str
    test_class: type["AcceptanceTest"]
    method_name: str

    @property
    def full_name(self) -> str:
        return f"{self.module_name}::{self.test_class.__name__}::{self.method_name}"


def discover_tests() -> list[TestCase]:
    """Discover all test cases in the tests package by scanning for acceptance_test_*.py files."""
    from .runner import AcceptanceTest

    tests_dir = Path(__file__).parent / "tests"
    base_package = "posthog.temporal.ingestion_acceptance_test.tests"

    tests: list[TestCase] = []

    for test_file in tests_dir.rglob("acceptance_test_*.py"):
        relative_path = test_file.relative_to(tests_dir)
        module_parts = list(relative_path.with_suffix("").parts)
        module_name = f"{base_package}.{'.'.join(module_parts)}"

        module = importlib.import_module(module_name)

        for name, cls in inspect.getmembers(module, inspect.isclass):
            if not name.startswith("Test"):
                continue
            if not issubclass(cls, AcceptanceTest):
                continue

            for method_name in dir(cls):
                if not method_name.startswith("test_"):
                    continue

                tests.append(
                    TestCase(
                        module_name=test_file.stem,
                        test_class=cls,
                        method_name=method_name,
                    )
                )

    return tests
