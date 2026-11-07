from pathlib import Path
from tempfile import TemporaryDirectory

import unittest

from parameterized import parameterized

from bin.mypy_cache_key import config_files, config_hash


class TestMypyCacheKey(unittest.TestCase):
    def test_hash_files_compatibility(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "nested").mkdir()
            (root / "nested" / "pyproject.toml").write_text("nested")
            (root / "pyproject.toml").write_text("root")
            (root / "uv.lock").write_text("lock")
            (root / "nested" / "uv.lock").write_text("ignored")
            (root / "nested" / "source.py").write_text("ignored")
            self.assertEqual(
                config_hash(root),
                "5dd6b2aa02c88e9fde7f9ed18ce3c8d2a3ebd4616678a80089cb6c7a7570abde",
            )

    @parameterized.expand(
        [
            (name, operation)
            for name in ("pyproject.toml", "nested/mypy.ini", "uv.lock")
            for operation in ("edit", "delete")
        ]
    )
    def test_config_changes_invalidate_hash(self, name: str, operation: str) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            file = root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("before")
            before = config_hash(root)
            if operation == "edit":
                file.write_text("after")
            else:
                file.unlink()
            self.assertNotEqual(config_hash(root), before)

    def test_symlinks_and_directory_matches(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "nested").mkdir()
            (root / "nested" / "mypy.ini").write_text("config")
            (root / "alias").symlink_to(root / "nested", target_is_directory=True)
            (root / "nested" / "cycle").symlink_to(root, target_is_directory=True)
            (root / "broken").symlink_to(root / "missing")
            (root / "pyproject.toml").symlink_to(root / "nested" / "mypy.ini")
            (root / "mypy.ini").mkdir()
            (root / "mypy.ini" / "data").write_text("directory match")
            self.assertEqual(
                [str(file.relative_to(root)) for file in config_files(root)],
                ["alias/mypy.ini", "mypy.ini/data", "nested/mypy.ini", "pyproject.toml"],
            )

    def test_no_matches(self) -> None:
        with TemporaryDirectory() as temporary:
            self.assertEqual(config_hash(Path(temporary)), "")
