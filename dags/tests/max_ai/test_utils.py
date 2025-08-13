from datetime import datetime

from django.test import override_settings

from dags.max_ai.utils import compose_postgres_dump_path, get_consistent_hash_suffix


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
    file_name = "test_dump"
    code_version = "v1.0"

    with override_settings(OBJECT_STORAGE_MAX_AI_EVALS_FOLDER="test-bucket"):
        result = compose_postgres_dump_path(project_id, file_name, code_version)

        # Should contain the project ID in path
        assert f"/{project_id}/" in result

        # Should start with the mocked folder path
        assert result.startswith("test-bucket/models/")

        # Should end with .avro extension
        assert result.endswith(".avro")

        # Should contain the file name and hash suffix
        assert file_name in result

        # Should be deterministic - same inputs produce same output
        result2 = compose_postgres_dump_path(project_id, file_name, code_version)
        assert result == result2

        # Different code version should produce different path
        result_different_version = compose_postgres_dump_path(project_id, file_name, "v2.0")
        assert result != result_different_version
