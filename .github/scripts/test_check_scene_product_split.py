import sys
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent / "check-scene-product-split.py"


def load_module_rooted_at(tmp_path: Path):
    spec = importlib.util.spec_from_file_location("check_scene_product_split", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered before exec: the script uses `from __future__ import annotations`, so
    # @dataclass resolves its field annotations by looking its own module up in sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.REPO_ROOT = tmp_path
    module.SCENES_ROOT = tmp_path / "frontend/src/scenes"
    module.PRODUCTS_ROOT = tmp_path / "products"
    module.BASELINE_FILE = module.SCENES_ROOT / "product_split_baseline.txt"
    return module


def make_files(root: Path, count: int, *, subdir: str = "", suffix: str = ".tsx") -> None:
    target = root / subdir if subdir else root
    target.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (target / f"File{i}{suffix}").write_text("export const x = 1\n")


@pytest.fixture
def repo(tmp_path: Path):
    mod = load_module_rooted_at(tmp_path)
    mod.SCENES_ROOT.mkdir(parents=True)
    mod.PRODUCTS_ROOT.mkdir(parents=True)
    return mod


def scene(mod, name: str, count: int, **kwargs) -> None:
    make_files(mod.SCENES_ROOT / name, count, **kwargs)


def product(mod, name: str, count: int, **kwargs) -> None:
    make_files(mod.PRODUCTS_ROOT / name / "frontend", count, **kwargs)


def run(mod, argv: list[str] | None = None) -> int:
    old = sys.argv
    sys.argv = ["check-scene-product-split.py", *(argv or [])]
    try:
        return mod.main()
    finally:
        sys.argv = old


class TestSceneProductSplitGuard:
    def test_mode_is_derived_from_which_side_holds_more_files(self, repo):
        scene(repo, "surveys", 10)
        product(repo, "surveys", 3)
        scene(repo, "actions", 1)
        product(repo, "actions", 8)
        found = repo.scan_current()
        assert found["surveys"].mode == "observe"
        assert found["actions"].mode == "enforce"

    def test_generated_files_do_not_count_as_migration_progress(self, repo):
        scene(repo, "surveys", 4)
        product(repo, "surveys", 1)
        product(repo, "surveys", 40, subdir="generated")
        found = repo.scan_current()
        assert found["surveys"].product_files == 1
        assert found["surveys"].mode == "observe", "orval output must not flip a tree into enforce"

    @pytest.mark.parametrize("scene_name,product_name", [("data-warehouse", "data_warehouse"), ("surveys", "surveys")])
    def test_kebab_scene_matches_snake_product(self, repo, scene_name, product_name):
        # A normalization break silently drops the dir to `unowned`, disabling the guard
        # rather than failing it.
        scene(repo, scene_name, 2)
        product(repo, product_name, 2)
        assert repo.scan_current()[scene_name].product == product_name

    @pytest.mark.parametrize(
        "scene_files,product_files,expected_exit",
        [(2, 9, 1), (50, 1, 0)],
        ids=["enforced_tree_fails", "unmigrated_tree_warns"],
    )
    def test_growth_is_gated_by_tier(self, repo, scene_files, product_files, expected_exit):
        scene(repo, "actions", scene_files)
        product(repo, "actions", product_files)
        run(repo, ["--regenerate-baseline"])
        make_files(repo.SCENES_ROOT / "actions", 1, suffix=".added.tsx")
        assert run(repo) == expected_exit

    @pytest.mark.parametrize(
        "new_dir,create_product,expected_exit",
        [("links", True, 1), ("onboarding", False, 0)],
        ids=["product_counterpart_fails", "app_level_scene_warns"],
    )
    def test_new_scene_dir_fails_only_when_a_product_owns_the_name(self, repo, new_dir, create_product, expected_exit):
        scene(repo, "settings", 3)
        run(repo, ["--regenerate-baseline"])
        scene(repo, new_dir, 1)
        if create_product:
            (repo.PRODUCTS_ROOT / new_dir).mkdir(parents=True, exist_ok=True)
        assert run(repo) == expected_exit

    def test_deleted_tree_reports_as_fully_migrated(self, repo, capsys):
        # A fully removed dir drops out of the scan entirely, so it once reported
        # "Baseline matches" and left a stale entry behind.
        scene(repo, "exports", 4)
        product(repo, "exports", 1)
        run(repo, ["--regenerate-baseline"])
        for path in (repo.SCENES_ROOT / "exports").iterdir():
            path.unlink()
        assert run(repo) == 0
        assert "fully migrated" in capsys.readouterr().out

    def test_unchanged_tree_passes(self, repo, capsys):
        # The spurious-failure guard: this firing would block every frontend PR.
        scene(repo, "surveys", 5)
        product(repo, "surveys", 2)
        run(repo, ["--regenerate-baseline"])
        assert run(repo) == 0
        assert "Baseline matches" in capsys.readouterr().out
