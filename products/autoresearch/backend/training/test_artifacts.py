from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.storage.object_storage import ObjectStorageError

from products.autoresearch.backend.training import artifacts
from products.autoresearch.backend.training.artifacts import (
    BundleNotFound,
    InvalidArtifactContent,
    InvalidArtifactPath,
    bundle_prefix,
    delete_artifact,
    list_artifacts,
    normalize_artifact_path,
    read_artifact,
    write_artifact,
)

ANCHORED_SQL = b"SELECT a.person_id AS distinct_id, count() AS c FROM {anchors} a GROUP BY a.person_id"


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


class TestNormalizeArtifactPath(SimpleTestCase):
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


@override_settings(OBJECT_STORAGE_ENABLED=True)
class TestArtifactStorage(SimpleTestCase):
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
        with self.assertRaises(InvalidArtifactContent):
            write_artifact(self.prefix, "eda/big.bin", b"x" * (artifacts.MAX_ARTIFACT_BYTES + 1))

    @parameterized.expand([("traversal", "../escape.py"), ("key_too_long", "eda/" + "x" * 1100 + ".txt")])
    def test_write_validates_path(self, _name: str, path: str) -> None:
        with self.assertRaises(InvalidArtifactPath):
            write_artifact(self.prefix, path, b"a")
        self.assertEqual(self.fake.store, {})

    @parameterized.expand(
        [
            ("empty_script", "train.py", b"   \n"),
            ("not_utf8", "predict.py", b"\xff\xfe"),
            (
                "feature_sql_reads_wall_clock",
                "features.sql",
                b"SELECT a.person_id AS distinct_id FROM {anchors} a WHERE now() > 0",
            ),
            ("feature_sql_unanchored", "features.sql", b"SELECT person_id AS distinct_id FROM events"),
        ]
    )
    def test_bundle_files_are_validated_before_they_are_stored(self, _name: str, path: str, content: bytes) -> None:
        with self.assertRaises(InvalidArtifactContent):
            write_artifact(self.prefix, path, content)
        self.assertEqual(self.fake.store, {})

    def test_valid_feature_sql_upload_is_stored(self) -> None:
        write_artifact(self.prefix, "features.sql", ANCHORED_SQL)
        self.assertEqual(read_artifact(self.prefix, "features.sql"), ANCHORED_SQL)

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    def test_write_refuses_when_object_storage_is_disabled(self) -> None:
        with self.assertRaises(ObjectStorageError):
            write_artifact(self.prefix, "train.py", b"a")
        self.assertEqual(self.fake.store, {})
