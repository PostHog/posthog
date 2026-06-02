from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.autoresearch.backend import artifacts
from products.autoresearch.backend.artifacts import (
    BundleNotFound,
    InvalidArtifactPath,
    bundle_prefix,
    delete_artifact,
    list_artifacts,
    normalize_artifact_path,
    read_artifact,
    write_artifact,
)


class _InMemoryStorage:
    """Minimal stand-in for posthog.storage.object_storage's module functions."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def write(self, key: str, content, extras=None, bucket=None) -> None:
        self.store[key] = content if isinstance(content, bytes) else content.encode("utf-8")

    def read_bytes(self, key: str, bucket=None, *, missing_ok: bool = False):
        if key in self.store:
            return self.store[key]
        if missing_ok:
            return None
        raise FileNotFoundError(key)

    def delete(self, key: str, bucket=None) -> None:
        self.store.pop(key, None)

    def list_objects(self, prefix: str):
        keys = [k for k in self.store if k.startswith(prefix)]
        return keys or None


class TestNormalizeArtifactPath(BaseTest):
    @parameterized.expand(
        [
            ("plain", "train.py", "train.py"),
            ("leading_slash", "/train.py", "train.py"),
            ("subdir", "eda/iter-3.ipynb", "eda/iter-3.ipynb"),
            ("whitespace", "  features.sql  ", "features.sql"),
        ]
    )
    def test_valid_paths(self, _name: str, path: str, expected: str) -> None:
        self.assertEqual(normalize_artifact_path(path), expected)

    @parameterized.expand(
        [
            ("empty", ""),
            ("traversal", "../secrets"),
            ("nested_traversal", "eda/../../etc/passwd"),
            ("dot_segment", "eda/./x"),
            ("space_in_segment", "my file.py"),
            ("slash_only", "/"),
        ]
    )
    def test_invalid_paths(self, _name: str, path: str) -> None:
        with self.assertRaises(InvalidArtifactPath):
            normalize_artifact_path(path)


class TestArtifactStorage(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.fake = _InMemoryStorage()
        patcher = patch.object(artifacts, "object_storage", self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.prefix = bundle_prefix(team_id=1, pipeline_id="pid", training_run_id="rid")

    def test_write_then_read_roundtrip(self) -> None:
        stored = write_artifact(self.prefix, "train.py", b"print('hi')")
        self.assertEqual(stored.path, "train.py")
        self.assertEqual(stored.size_bytes, 11)
        self.assertEqual(read_artifact(self.prefix, "train.py"), b"print('hi')")

    def test_read_missing_raises(self) -> None:
        with self.assertRaises(BundleNotFound):
            read_artifact(self.prefix, "nope.py")

    def test_list_returns_relative_sorted_paths(self) -> None:
        write_artifact(self.prefix, "train.py", b"a")
        write_artifact(self.prefix, "predict.py", b"b")
        write_artifact(self.prefix, "eda/iter-1.ipynb", b"c")
        self.assertEqual(list_artifacts(self.prefix), ["eda/iter-1.ipynb", "predict.py", "train.py"])

    def test_delete_reports_existence(self) -> None:
        write_artifact(self.prefix, "train.py", b"a")
        self.assertTrue(delete_artifact(self.prefix, "train.py"))
        self.assertFalse(delete_artifact(self.prefix, "train.py"))

    def test_oversize_upload_rejected(self) -> None:
        with self.assertRaises(InvalidArtifactPath):
            write_artifact(self.prefix, "train.py", b"x" * (artifacts.MAX_ARTIFACT_BYTES + 1))

    def test_write_validates_path(self) -> None:
        with self.assertRaises(InvalidArtifactPath):
            write_artifact(self.prefix, "../escape.py", b"a")
