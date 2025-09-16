from datetime import datetime
from typing import Any, cast
from uuid import UUID

import pytest

from django.conf import settings

from dagster_aws.s3 import S3Resource
from fastavro import reader
from pydantic_avro import AvroBase

from dags.max_ai.utils import (
    EVALS_S3_BUCKET,
    EVALS_S3_PREFIX,
    EvaluationResults,
    ResultsFormatter,
    check_dump_exists,
    compose_clickhouse_dump_path,
    compose_postgres_dump_path,
    dump_model,
    format_results,
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


# Tests for format_results function


def test_format_results_basic():
    """Test basic formatting with single result and no previous results."""
    dataset_id = UUID("12345678-1234-5678-9012-123456789012")
    dataset_name = "Test Dataset"
    experiment_id = "exp_123"

    results: EvaluationResults = [
        {
            "project_name": "test_experiment",
            "scores": {"accuracy": {"score": 0.85}, "precision": {"score": 0.92}},
            "metrics": {
                "duration": {"metric": 12.5},
                "total_tokens": {"metric": 1500},
                "estimated_cost": {"metric": 0.0125},
            },
        }
    ]

    blocks, markdown = format_results(dataset_id, dataset_name, experiment_id, results)

    # Check structure
    assert isinstance(blocks, list)
    assert len(blocks) == 1
    assert blocks[0]["type"] == "section"
    assert blocks[0]["text"]["type"] == "mrkdwn"

    # Check content
    assert "Test Dataset" in markdown
    assert "test_experiment" in markdown
    assert "85.00%" in markdown
    assert "92.00%" in markdown
    assert "12.50 s" in markdown
    assert "1500 tokens" in markdown
    assert "$0.0125" in markdown
    assert "🆕" in markdown  # New experiment emoji


def test_format_results_with_comparison():
    """Test formatting with previous results for comparison."""
    dataset_id = UUID("12345678-1234-5678-9012-123456789012")
    dataset_name = "Test Dataset"
    experiment_id = "exp_123"

    results: EvaluationResults = [
        {
            "project_name": "test_experiment",
            "scores": {"accuracy": {"score": 0.88}, "precision": {"score": 0.85}},
            "metrics": {"duration": {"metric": 10.0}, "total_tokens": {"metric": 1200}},
        }
    ]

    prev_results: EvaluationResults = [
        {"project_name": "test_experiment", "scores": {"accuracy": {"score": 0.85}, "precision": {"score": 0.90}}}
    ]

    blocks, markdown = format_results(dataset_id, dataset_name, experiment_id, results, prev_results)

    # Check improvement indicators
    assert "🟢" in markdown  # Improvement emoji for accuracy
    assert "🔴" in markdown  # Regression emoji for precision
    assert "+3.00%" in markdown  # Accuracy improvement
    assert "-5.00%" in markdown  # Precision regression
    assert "improvements: 1, regressions: 0" in markdown  # For accuracy
    assert "improvements: 0, regressions: 1" in markdown  # For precision


def test_format_results_multiple_experiments():
    """Test formatting with multiple experiments."""
    dataset_id = UUID("12345678-1234-5678-9012-123456789012")
    dataset_name = "Multi Experiment Dataset"
    experiment_id = "exp_multi"

    results: EvaluationResults = [
        {
            "project_name": "experiment_1",
            "scores": {"accuracy": {"score": 0.80}},
            "metrics": {"duration": {"metric": 5.0}},
        },
        {
            "project_name": "experiment_2",
            "scores": {"precision": {"score": 0.75}},
            "metrics": {"total_tokens": {"metric": 800}},
        },
    ]

    blocks, markdown = format_results(dataset_id, dataset_name, experiment_id, results)

    # Should contain both experiments
    assert "experiment_1" in markdown
    assert "experiment_2" in markdown
    assert "80.00%" in markdown
    assert "75.00%" in markdown
    assert "Evaluated **2** experiments, comprising **2** metrics" in markdown


def test_format_results_exact_zero_change():
    """Test formatting when scores are exactly the same."""
    dataset_id = UUID("12345678-1234-5678-9012-123456789012")
    dataset_name = "Identical Dataset"
    experiment_id = "exp_identical"

    results: EvaluationResults = [{"project_name": "identical_experiment", "scores": {"accuracy": {"score": 0.85}}}]

    prev_results: EvaluationResults = [
        {"project_name": "identical_experiment", "scores": {"accuracy": {"score": 0.85}}}
    ]

    blocks, markdown = format_results(dataset_id, dataset_name, experiment_id, results, prev_results)

    # Should show exact zero change
    assert "🔵" in markdown  # No change emoji
    assert "±0.00%" in markdown  # Exact zero change
    assert "improvements: 0, regressions: 0" in markdown


def test_format_results_missing_metrics():
    """Test formatting when metrics are missing or incomplete."""
    dataset_id = UUID("12345678-1234-5678-9012-123456789012")
    dataset_name = "Sparse Dataset"
    experiment_id = "exp_sparse"

    results: EvaluationResults = [
        {
            "project_name": "sparse_experiment",
            "scores": {"accuracy": {"score": 0.70}},
            # No metrics field
        },
        {
            "project_name": "partial_metrics_experiment",
            "scores": {"precision": {"score": 0.65}},
            "metrics": {
                "duration": {"metric": 3.0}
                # Missing other metrics
            },
        },
    ]

    blocks, markdown = format_results(dataset_id, dataset_name, experiment_id, results)

    # Should handle missing metrics gracefully
    assert "No metrics reported" in markdown
    assert "3.00 s" in markdown  # Partial metrics should still show


def test_format_results_empty_results():
    """Test formatting with empty results list."""
    dataset_id = UUID("12345678-1234-5678-9012-123456789012")
    dataset_name = "Empty Dataset"
    experiment_id = "exp_empty"

    results: EvaluationResults = []

    blocks, markdown = format_results(dataset_id, dataset_name, experiment_id, results)

    # Should handle empty results
    assert "Empty Dataset" in markdown
    assert "Evaluated **0** experiments, comprising **0** metrics" in markdown


def test_format_results_non_numeric_scores():
    """Test formatting with non-numeric score values."""
    dataset_id = UUID("12345678-1234-5678-9012-123456789012")
    dataset_name = "String Score Dataset"
    experiment_id = "exp_string"

    results: EvaluationResults = [
        {
            "project_name": "string_score_experiment",
            "scores": {"quality": {"score": "excellent"}, "status": {"score": "passed"}},
        }
    ]

    blocks, markdown = format_results(dataset_id, dataset_name, experiment_id, results)

    # Should handle non-numeric scores
    assert "excellent" in markdown
    assert "passed" in markdown
    # Should not try to format as percentage
    assert "excellent%" not in markdown


def test_format_results_missing_previous_experiment():
    """Test comparison when previous results don't contain matching experiment."""
    dataset_id = UUID("12345678-1234-5678-9012-123456789012")
    dataset_name = "Mismatch Dataset"
    experiment_id = "exp_mismatch"

    results: EvaluationResults = [{"project_name": "new_experiment", "scores": {"accuracy": {"score": 0.88}}}]

    prev_results: EvaluationResults = [
        {
            "project_name": "old_experiment",  # Different name
            "scores": {"accuracy": {"score": 0.85}},
        }
    ]

    blocks, markdown = format_results(dataset_id, dataset_name, experiment_id, results, prev_results)

    # Should treat as new experiment since no matching previous result
    assert "🆕" in markdown
    assert "new_experiment" in markdown
    # Should not show comparison indicators
    assert "🟢" not in markdown
    assert "🔴" not in markdown


def test_format_results_traces_filter_generation():
    """Test that traces filter URLs are properly generated."""
    dataset_id = UUID("12345678-1234-5678-9012-123456789012")
    dataset_name = "Traces Dataset"
    experiment_id = "exp_traces_123"

    results: EvaluationResults = [{"project_name": "traced_experiment", "scores": {"accuracy": {"score": 0.90}}}]

    blocks, markdown = format_results(dataset_id, dataset_name, experiment_id, results)

    # Should contain properly encoded traces URL
    assert "https://us.posthog.com/llm-analytics/traces?filters=" in markdown
    assert "traced_experiment" in markdown
    assert "exp_traces_123" in markdown
    # URL should be properly encoded
    assert "%22" in markdown  # URL encoded quotes


def test_format_results_dataset_link():
    """Test that dataset link is properly formatted."""
    dataset_id = UUID("12345678-1234-5678-9012-123456789012")
    dataset_name = "Linked Dataset"
    experiment_id = "exp_link"

    results: EvaluationResults = [{"project_name": "linked_experiment", "scores": {"accuracy": {"score": 0.95}}}]

    blocks, markdown = format_results(dataset_id, dataset_name, experiment_id, results)

    # Should contain dataset link with correct UUID
    expected_link = f"https://us.posthog.com/llm-analytics/datasets/{dataset_id}"
    assert expected_link in markdown
    assert f"[{dataset_name}]" in markdown


def test_results_formatter_basic():
    """Test basic formatting with ResultsFormatter class."""
    dataset_id = UUID("12345678-1234-5678-9012-123456789012")
    dataset_name = "Test Dataset"
    experiment_id = "exp_123"

    results: EvaluationResults = [
        {
            "project_name": "test_experiment",
            "scores": {"accuracy": {"score": 0.85}, "precision": {"score": 0.92}},
            "metrics": {
                "duration": {"metric": 12.5},
                "total_tokens": {"metric": 1500},
                "estimated_cost": {"metric": 0.0125},
            },
        }
    ]

    formatter = ResultsFormatter(dataset_id, dataset_name, experiment_id)
    blocks, markdown = formatter.format(results)

    # Check structure
    assert isinstance(blocks, list)
    assert len(blocks) == 1
    assert blocks[0]["type"] == "section"
    assert blocks[0]["text"]["type"] == "mrkdwn"

    # Check content
    assert "Test Dataset" in markdown
    assert "test_experiment" in markdown
    assert "85.00%" in markdown
    assert "92.00%" in markdown
    assert "12.50 s" in markdown
    assert "1500 tokens" in markdown
    assert "$0.0125" in markdown
    assert "🆕" in markdown  # New experiment emoji


def test_results_formatter_with_comparison():
    """Test ResultsFormatter with previous results for comparison."""
    dataset_id = UUID("12345678-1234-5678-9012-123456789012")
    dataset_name = "Test Dataset"
    experiment_id = "exp_123"

    results: EvaluationResults = [
        {
            "project_name": "test_experiment",
            "scores": {"accuracy": {"score": 0.88}, "precision": {"score": 0.85}},
            "metrics": {"duration": {"metric": 10.0}, "total_tokens": {"metric": 1200}},
        }
    ]

    prev_results: EvaluationResults = [
        {"project_name": "test_experiment", "scores": {"accuracy": {"score": 0.85}, "precision": {"score": 0.90}}}
    ]

    formatter = ResultsFormatter(dataset_id, dataset_name, experiment_id)
    blocks, markdown = formatter.format(results, prev_results)

    # Check improvement indicators
    assert "🟢" in markdown  # Improvement emoji for accuracy
    assert "🔴" in markdown  # Regression emoji for precision
    assert "+3.00%" in markdown  # Accuracy improvement
    assert "-5.00%" in markdown  # Precision regression
    assert "improvements: 1, regressions: 0" in markdown  # For accuracy
    assert "improvements: 0, regressions: 1" in markdown  # For precision


def test_results_formatter_find_previous_result():
    """Test _find_previous_result method."""
    dataset_id = UUID("12345678-1234-5678-9012-123456789012")
    dataset_name = "Test Dataset"
    experiment_id = "exp_123"

    formatter = ResultsFormatter(dataset_id, dataset_name, experiment_id)

    # Test with None prev_results
    result = {"project_name": "test_experiment"}
    assert formatter._find_previous_result(result, None) is None

    # Test with empty prev_results
    assert formatter._find_previous_result(result, []) is None

    # Test with matching previous result
    prev_results = [
        {"project_name": "other_experiment", "scores": {"accuracy": {"score": 0.80}}},
        {"project_name": "test_experiment", "scores": {"accuracy": {"score": 0.85}}},
    ]
    found = formatter._find_previous_result(result, prev_results)
    assert found is not None
    assert found["project_name"] == "test_experiment"
    assert found["scores"]["accuracy"]["score"] == 0.85

    # Test with no matching previous result
    result_no_match = {"project_name": "nonexistent_experiment"}
    assert formatter._find_previous_result(result_no_match, prev_results) is None


def test_results_formatter_format_metrics():
    """Test _format_metrics method."""
    dataset_id = UUID("12345678-1234-5678-9012-123456789012")
    dataset_name = "Test Dataset"
    experiment_id = "exp_123"

    formatter = ResultsFormatter(dataset_id, dataset_name, experiment_id)

    # Test with no metrics
    result_no_metrics: dict[str, Any] = {}
    assert formatter._format_metrics(result_no_metrics) == "No metrics reported"

    # Test with empty metrics
    result_empty_metrics: dict[str, Any] = {"metrics": {}}
    assert formatter._format_metrics(result_empty_metrics) == "No metrics reported"

    # Test with all metrics
    result_all_metrics = {
        "metrics": {
            "duration": {"metric": 15.5},
            "total_tokens": {"metric": 2000},
            "estimated_cost": {"metric": 0.025},
        }
    }
    metrics_text = formatter._format_metrics(result_all_metrics)
    assert "⏱️ 15.50 s" in metrics_text
    assert "🔢 2000 tokens" in metrics_text
    assert "💵 $0.0250 in tokens" in metrics_text

    # Test with partial metrics
    result_partial_metrics = {"metrics": {"duration": {"metric": 8.0}}}
    metrics_text = formatter._format_metrics(result_partial_metrics)
    assert "⏱️ 8.00 s" in metrics_text
    assert "tokens" not in metrics_text
    assert "$" not in metrics_text


def test_results_formatter_build_traces_url():
    """Test _build_traces_url method."""
    dataset_id = UUID("12345678-1234-5678-9012-123456789012")
    dataset_name = "Test Dataset"
    experiment_id = "exp_traces_123"

    formatter = ResultsFormatter(dataset_id, dataset_name, experiment_id)

    result = {"project_name": "traced_experiment"}
    traces_url = formatter._build_traces_url(result)

    # Should contain properly encoded traces URL
    assert "https://us.posthog.com/llm-analytics/traces?filters=" in traces_url
    assert "traced_experiment" in traces_url
    assert "exp_traces_123" in traces_url
    # URL should be properly encoded
    assert "%22" in traces_url  # URL encoded quotes


def test_results_formatter_calculate_score_comparison():
    """Test _calculate_score_comparison method."""
    dataset_id = UUID("12345678-1234-5678-9012-123456789012")
    dataset_name = "Test Dataset"
    experiment_id = "exp_123"

    formatter = ResultsFormatter(dataset_id, dataset_name, experiment_id)

    # Test with no previous score data
    value: dict[str, Any] = {"score": 0.85}
    prev_result: dict[str, Any] = {"scores": {}}
    comparison, emoji = formatter._calculate_score_comparison("accuracy", value, prev_result)
    assert comparison is None
    assert emoji == "🆕"

    # Test with improvement
    prev_result = {"scores": {"accuracy": {"score": 0.80}}}
    comparison, emoji = formatter._calculate_score_comparison("accuracy", value, prev_result)
    assert comparison is not None
    assert "+5.00%" in comparison
    assert "improvements: 1, regressions: 0" in comparison
    assert emoji == "🟢"

    # Test with regression
    value = {"score": 0.75}
    comparison, emoji = formatter._calculate_score_comparison("accuracy", value, prev_result)
    assert comparison is not None
    assert "-5.00%" in comparison
    assert "improvements: 0, regressions: 1" in comparison
    assert emoji == "🔴"

    # Test with no change
    value = {"score": 0.80}
    comparison, emoji = formatter._calculate_score_comparison("accuracy", value, prev_result)
    assert comparison is not None
    assert "±0.00%" in comparison
    assert "improvements: 0, regressions: 0" in comparison
    assert emoji == "🔵"


def test_results_formatter_format_single_score():
    """Test _format_single_score method."""
    dataset_id = UUID("12345678-1234-5678-9012-123456789012")
    dataset_name = "Test Dataset"
    experiment_id = "exp_123"

    formatter = ResultsFormatter(dataset_id, dataset_name, experiment_id)

    # Test with numeric score and no previous result
    value: dict[str, Any] = {"score": 0.85}
    score_line = formatter._format_single_score("accuracy", value, None)
    assert "🆕 **accuracy**: **85.00%**" == score_line

    # Test with string score
    value = {"score": "excellent"}
    score_line = formatter._format_single_score("quality", value, None)
    assert "🆕 **quality**: **excellent**" == score_line

    # Test with comparison
    prev_result = {"scores": {"accuracy": {"score": 0.80}}}
    value = {"score": 0.85}
    score_line = formatter._format_single_score("accuracy", value, prev_result)
    assert "🟢 **accuracy**: **85.00%**" in score_line
    assert "+5.00%" in score_line


def test_results_formatter_empty_results():
    """Test ResultsFormatter with empty results list."""
    dataset_id = UUID("12345678-1234-5678-9012-123456789012")
    dataset_name = "Empty Dataset"
    experiment_id = "exp_empty"

    results: EvaluationResults = []

    formatter = ResultsFormatter(dataset_id, dataset_name, experiment_id)
    blocks, markdown = formatter.format(results)

    # Should handle empty results
    assert "Empty Dataset" in markdown
    assert "Evaluated **0** experiments, comprising **0** metrics" in markdown


def test_results_formatter_multiple_experiments():
    """Test ResultsFormatter with multiple experiments."""
    dataset_id = UUID("12345678-1234-5678-9012-123456789012")
    dataset_name = "Multi Experiment Dataset"
    experiment_id = "exp_multi"

    results: EvaluationResults = [
        {
            "project_name": "experiment_1",
            "scores": {"accuracy": {"score": 0.80}},
            "metrics": {"duration": {"metric": 5.0}},
        },
        {
            "project_name": "experiment_2",
            "scores": {"precision": {"score": 0.75}},
            "metrics": {"total_tokens": {"metric": 800}},
        },
    ]

    formatter = ResultsFormatter(dataset_id, dataset_name, experiment_id)
    blocks, markdown = formatter.format(results)

    # Should contain both experiments
    assert "experiment_1" in markdown
    assert "experiment_2" in markdown
    assert "80.00%" in markdown
    assert "75.00%" in markdown
    assert "Evaluated **2** experiments, comprising **2** metrics" in markdown
