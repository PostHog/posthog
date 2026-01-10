import pytest

from products.batch_exports.backend.temporal.destinations.azure_blob_batch_export import (
    COMPRESSION_EXTENSIONS,
    FILE_FORMAT_EXTENSIONS,
)
from products.batch_exports.backend.temporal.destinations.utils import get_key_prefix, get_manifest_key, get_object_key

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


@pytest.mark.parametrize(
    "file_format,compression,expected_filename",
    [
        ("JSONLines", None, "2024-01-01T00:00:00-2024-01-01T01:00:00.jsonl"),
        ("JSONLines", "gzip", "2024-01-01T00:00:00-2024-01-01T01:00:00.jsonl.gz"),
        ("JSONLines", "brotli", "2024-01-01T00:00:00-2024-01-01T01:00:00.jsonl.br"),
        ("JSONLines", "zstd", "2024-01-01T00:00:00-2024-01-01T01:00:00.jsonl.zst"),
        ("Parquet", None, "2024-01-01T00:00:00-2024-01-01T01:00:00.parquet"),
        ("Parquet", "gzip", "2024-01-01T00:00:00-2024-01-01T01:00:00.parquet.gz"),
        ("Parquet", "brotli", "2024-01-01T00:00:00-2024-01-01T01:00:00.parquet.br"),
        ("Parquet", "zstd", "2024-01-01T00:00:00-2024-01-01T01:00:00.parquet.zst"),
    ],
)
def test_get_object_key_generates_correct_extension(file_format, compression, expected_filename):
    key = get_object_key(
        prefix="exports/",
        data_interval_start="2024-01-01T00:00:00",
        data_interval_end="2024-01-01T01:00:00",
        batch_export_model=None,
        file_extension=FILE_FORMAT_EXTENSIONS[file_format],
        compression_extension=COMPRESSION_EXTENSIONS.get(compression),
    )
    assert key == f"exports/{expected_filename}"


def test_get_object_key_includes_file_number_when_splitting():
    key = get_object_key(
        prefix="exports/",
        data_interval_start="2024-01-01T00:00:00",
        data_interval_end="2024-01-01T01:00:00",
        batch_export_model=None,
        file_extension=FILE_FORMAT_EXTENSIONS["JSONLines"],
        compression_extension=None,
        file_number=5,
        include_file_number=True,
    )
    assert key == "exports/2024-01-01T00:00:00-2024-01-01T01:00:00-5.jsonl"


def test_get_key_prefix_substitutes_template_variables():
    prefix = get_key_prefix(
        prefix="{year}/{month}/{day}/",
        data_interval_start="2024-01-15T00:00:00",
        data_interval_end="2024-01-15T01:00:00",
        batch_export_model=None,
    )
    assert prefix == "2024/01/15/"


def test_get_key_prefix_returns_unchanged_on_invalid_template():
    prefix = get_key_prefix(
        prefix="{invalid_var}/data/",
        data_interval_start="2024-01-15T00:00:00",
        data_interval_end="2024-01-15T01:00:00",
        batch_export_model=None,
    )
    assert prefix == "{invalid_var}/data/"


def test_get_manifest_key_generates_correct_path():
    key = get_manifest_key(
        prefix="exports/",
        data_interval_start="2024-01-01T00:00:00",
        data_interval_end="2024-01-01T01:00:00",
        batch_export_model=None,
    )
    assert key == "exports/2024-01-01T00:00:00-2024-01-01T01:00:00_manifest.json"
