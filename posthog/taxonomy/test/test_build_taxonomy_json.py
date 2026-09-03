from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

GENERATOR = Path(__file__).resolve().parents[3] / "bin" / "build-taxonomy-json.py"


def _load_generator() -> ModuleType:
    # Loaded by path because the dash in the filename rules out a plain import.
    spec = importlib.util.spec_from_file_location("build_taxonomy_json", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _retarget(module: ModuleType, monkeypatch: pytest.MonkeyPatch, target: Path) -> None:
    # REPO_ROOT moves with OUTPUT because the drift branch prints
    # OUTPUT.relative_to(REPO_ROOT), which raises for a path outside the repo.
    monkeypatch.setattr(module, "REPO_ROOT", target.parent)
    monkeypatch.setattr(module, "OUTPUT", target)


class TestTaxonomyDriftDetection:
    @pytest.mark.parametrize("on_disk", [None, b"{}"])
    def test_check_reports_drift(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, on_disk: bytes | None) -> None:
        module = _load_generator()
        target = tmp_path / "core-filter-definitions-by-group.json"
        if on_disk is not None:
            target.write_bytes(on_disk)
        _retarget(module, monkeypatch, target)

        assert module.check() == 1

    def test_check_accepts_the_rendered_bytes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        module = _load_generator()
        target = tmp_path / "core-filter-definitions-by-group.json"
        target.write_bytes(module.render().encode())
        _retarget(module, monkeypatch, target)

        assert module.check() == 0
