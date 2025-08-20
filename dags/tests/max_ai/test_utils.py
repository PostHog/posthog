from datetime import datetime
from typing import Any, cast

import pytest
from dagster_aws.s3 import S3Resource
from django.conf import settings
from fastavro import reader
from pydantic_avro import AvroBase

from dags.max_ai.utils import (
    EVALS_S3_BUCKET,
    EVALS_S3_PREFIX,
    check_dump_exists,
    compose_clickhouse_dump_path,
    compose_postgres_dump_path,
    dump_model,
    get_consistent_hash_suffix,
)


def test_consistent_hash_suffix_same_period():
    """Test that hash is consistent within the same half-month period."""
    file_name = "test_file.txt"

    # Test first half of month (1st-14th)
    date_1st = datetime(2024, 1, 1)
    date_14th = datetime(2024, 1, 14)

    hash_1st = get_consistent_hash_suffix(file_name, date_1st)
    hash_14th = get_consistent_hash_suffix(file_name, date_14th)

    assert hash_1st == hash_14th, "Hash should be consistent within first half of month"

    # Test second half of month (15th-31st)
    date_15th = datetime(2024, 1, 15)
    date_31st = datetime(2024, 1, 31)

    hash_15th = get_consistent_hash_suffix(file_name, date_15th)
    hash_31st = get_consistent_hash_suffix(file_name, date_31st)

    assert hash_15th == hash_31st, "Hash should be consistent within second half of month"


def test_consistent_hash_suffix_different_periods():
    """Test that hash changes between different half-month periods."""
    file_name = "test_file.txt"

    # Test boundary between first and second half
    date_14th = datetime(2024, 1, 14)
    date_15th = datetime(2024, 1, 15)

    hash_14th = get_consistent_hash_suffix(file_name, date_14th)
    hash_15th = get_consistent_hash_suffix(file_name, date_15th)

    assert hash_14th != hash_15th, "Hash should change between first and second half of month"

    # Test boundary between months
    date_jan_31st = datetime(2024, 1, 31)
    date_feb_1st = datetime(2024, 2, 1)

    hash_jan_31st = get_consistent_hash_suffix(file_name, date_jan_31st)
    hash_feb_1st = get_consistent_hash_suffix(file_name, date_feb_1st)

    assert hash_jan_31st != hash_feb_1st, "Hash should change between different months"


def test_consistent_hash_suffix_with_code_version():
    """Test that code version affects the hash."""
    file_name = "test_file.txt"
    date = datetime(2024, 1, 1)

    hash_no_version = get_consistent_hash_suffix(file_name, date)
    hash_with_version = get_consistent_hash_suffix(file_name, date, "v1.0")
    hash_different_version = get_consistent_hash_suffix(file_name, date, "v2.0")

    assert hash_no_version != hash_with_version, "Hash should differ when code version is added"
    assert hash_with_version != hash_different_version, "Hash should differ for different code versions"


def test_hash_format():
    """Test that hash returns expected format (8 characters)."""
    file_name = "test_file.txt"
    date = datetime(2024, 1, 1)

    hash_result = get_consistent_hash_suffix(file_name, date)

    assert len(hash_result) == 8, "Hash should be 8 characters long"
    assert hash_result.isalnum(), "Hash should be alphanumeric"


def test_compose_postgres_dump_path():
    """Test that compose_postgres_dump_path generates correct S3 path with hash."""
    project_id = 123
    dir_name = "test_dump"
    code_version = "v1.0"

    result = compose_postgres_dump_path(project_id, dir_name, code_version)

    # Should contain the project ID in path
    assert f"/{project_id}/" in result

    # Should start with the mocked folder path
    assert result.startswith(f"{EVALS_S3_PREFIX}/postgres_models/")

    # Should end with .avro extension
    assert result.endswith(".avro")

    # Should contain the file name and hash suffix
    assert dir_name in result

    # Should be deterministic - same inputs produce same output
    result2 = compose_postgres_dump_path(project_id, dir_name, code_version)
    assert result == result2

    # Different code version should produce different path
    result_different_version = compose_postgres_dump_path(project_id, dir_name, "v2.0")
    assert result != result_different_version


def test_compose_clickhouse_dump_path():
    """Test that compose_clickhouse_dump_path generates correct S3 path with hash."""
    project_id = 123
    file_name = "test_dump"
    code_version = "v1.0"

    result = compose_clickhouse_dump_path(project_id, file_name, code_version)

    # Should contain the project ID in path
    assert f"/{project_id}/" in result

    # Should start with the correct folder path
    assert result.startswith(f"{EVALS_S3_PREFIX}/clickhouse_queries/")

    # Should end with .avro extension
    assert result.endswith(".avro")

    # Should contain the file name and hash suffix
    assert file_name in result

    # Should be deterministic - same inputs produce same output
    result2 = compose_clickhouse_dump_path(project_id, file_name, code_version)
    assert result == result2

    # Different code version should produce different path
    result_different_version = compose_clickhouse_dump_path(project_id, file_name, "v2.0")
    assert result != result_different_version

    # Test without code version
    result_no_version = compose_clickhouse_dump_path(project_id, file_name)
    assert result != result_no_version


# Test schema for dump_model tests
class DummySchema(AvroBase):
    name: str
    value: int


@pytest.fixture
def s3_resource():
    return S3Resource(
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
    )


def test_dump_model_creates_avro_file(s3_resource):
    """Test that dump_model creates an Avro file with correct data in S3."""
    file_key = "test/path/data.avro"

    test_models = [
        DummySchema(name="test1", value=1),
        DummySchema(name="test2", value=2),
    ]

    with dump_model(s3=s3_resource, schema=DummySchema, file_key=file_key) as dump:
        dump(test_models)

    uploaded_file = s3_resource.get_client().get_object(Bucket=EVALS_S3_BUCKET, Key=file_key)["Body"]

    # Verify the uploaded file contains valid Avro data
    records = list(cast(list[dict[str, Any]], reader(uploaded_file)))
    assert len(records) == 2
    assert records[0]["name"] == "test1"
    assert records[0]["value"] == 1
    assert records[1]["name"] == "test2"
    assert records[1]["value"] == 2


def test_check_dump_exists(s3_resource):
    """Test that check_dump_exists correctly identifies existing and non-existing files."""
    existing_file_key = "test/path/existing_file.avro"
    non_existing_file_key = "test/path/non_existing_file.avro"

    # First create a file
    test_models = [DummySchema(name="test", value=42)]
    with dump_model(s3=s3_resource, schema=DummySchema, file_key=existing_file_key) as dump:
        dump(test_models)

    # Test that existing file is found
    assert check_dump_exists(s3_resource, existing_file_key) is True

    # Test that non-existing file returns False
    assert check_dump_exists(s3_resource, non_existing_file_key) is False
