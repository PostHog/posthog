import sys
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def load_script_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[2] / ".github/scripts/check-dorny-paths-filter.py"
    spec = importlib.util.spec_from_file_location("check_dorny_paths_filter", script_path)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("workflow_contents", "expected_text", "unexpected_text"),
    [
        (
            "name: Broken workflow\njobs:\n  test: [\n",
            "Found 1 workflow parse error(s):",
            "unsafe dorny/paths-filter negation",
        ),
        (
            """name: Dorny workflow
jobs:
  test:
    steps:
      - uses: dorny/paths-filter@v3
        with:
          filters: |
            docs:
              - 'docs/**'
              - '!docs/private/**'
""",
            "Found 1 unsafe dorny/paths-filter negation(s):",
            "workflow parse error",
        ),
    ],
)
def test_main_reports_failure_category(
    workflow_contents: str, expected_text: str, unexpected_text: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    module = load_script_module()

    (tmp_path / "test.yml").write_text(workflow_contents)

    with pytest.raises(SystemExit, match="1"):
        module.main(tmp_path)

    output = capsys.readouterr().out
    assert expected_text in output
    assert unexpected_text not in output


def test_main_reports_all_negation_patterns(tmp_path: Path, capsys) -> None:
    module = load_script_module()

    (tmp_path / "test.yml").write_text(
        """name: Dorny workflow
jobs:
  test:
    steps:
      - id: changes
        uses: dorny/paths-filter@v3
        with:
          filters: |
            docs:
              - 'docs/**'
              - '!docs/private/**'
            backend:
              - 'posthog/**'
              - '!posthog/test/**'
""",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="1"):
        module.main(tmp_path)

    output = capsys.readouterr().out
    assert "filter 'docs' uses negation '!docs/private/**'" in output
    assert "filter 'backend' uses negation '!posthog/test/**'" in output
