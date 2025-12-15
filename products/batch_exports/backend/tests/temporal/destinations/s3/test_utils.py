import pytest

from products.batch_exports.backend.temporal.destinations.s3_batch_export import S3InsertInputs, get_s3_key

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]

base_inputs = {"bucket_name": "test", "region": "test", "team_id": 1}


@pytest.mark.parametrize(
    "inputs,expected",
    [
        (
            S3InsertInputs(
                prefix="/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,  # type: ignore
            ),
            "2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="invalid-template-variables-{invalid}",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,  # type: ignore
            ),
            "invalid-template-variables-{invalid}/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="invalid-format-spec-{data_interval_start:hour}",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,  # type: ignore
            ),
            "invalid-format-spec-{data_interval_start:hour}/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,  # type: ignore
            ),
            "2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                compression="gzip",
                **base_inputs,  # type: ignore
            ),
            "2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl.gz",
        ),
        (
            S3InsertInputs(
                prefix="",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                compression="brotli",
                **base_inputs,  # type: ignore
            ),
            "2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl.br",
        ),
        (
            S3InsertInputs(
                prefix="my-fancy-prefix",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,  # type: ignore
            ),
            "my-fancy-prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="/my-fancy-prefix",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,  # type: ignore
            ),
            "my-fancy-prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="my-fancy-prefix",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                compression="gzip",
                **base_inputs,  # type: ignore
            ),
            "my-fancy-prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl.gz",
        ),
        (
            S3InsertInputs(
                prefix="my-fancy-prefix",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                compression="brotli",
                **base_inputs,  # type: ignore
            ),
            "my-fancy-prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl.br",
        ),
        (
            S3InsertInputs(
                prefix="my-fancy-prefix-with-a-forwardslash/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,  # type: ignore
            ),
            "my-fancy-prefix-with-a-forwardslash/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="/my-fancy-prefix-with-a-forwardslash/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,  # type: ignore
            ),
            "my-fancy-prefix-with-a-forwardslash/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="nested/prefix/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,  # type: ignore
            ),
            "nested/prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="/nested/prefix/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,  # type: ignore
            ),
            "nested/prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="/nested/prefix/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                compression="gzip",
                **base_inputs,  # type: ignore
            ),
            "nested/prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl.gz",
        ),
        (
            S3InsertInputs(
                prefix="/nested/prefix/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                compression="brotli",
                **base_inputs,  # type: ignore
            ),
            "nested/prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl.br",
        ),
        (
            S3InsertInputs(
                prefix="/nested/prefix/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                file_format="Parquet",
                compression="snappy",
                **base_inputs,  # type: ignore
            ),
            "nested/prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.parquet.sz",
        ),
        (
            S3InsertInputs(
                prefix="/nested/prefix/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                file_format="Parquet",
                **base_inputs,  # type: ignore
            ),
            "nested/prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.parquet",
        ),
        (
            S3InsertInputs(
                prefix="/nested/prefix/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                compression="gzip",
                file_format="Parquet",
                **base_inputs,  # type: ignore
            ),
            "nested/prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.parquet.gz",
        ),
        (
            S3InsertInputs(
                prefix="/nested/prefix/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                compression="brotli",
                file_format="Parquet",
                **base_inputs,  # type: ignore
            ),
            "nested/prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.parquet.br",
        ),
        (
            S3InsertInputs(
                prefix="/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                max_file_size_mb=1,
                **base_inputs,  # type: ignore
            ),
            "2023-01-01 00:00:00-2023-01-01 01:00:00-0.jsonl",
        ),
    ],
)
def test_get_s3_key(inputs, expected):
    """Test the get_s3_key function renders the expected S3 key given inputs."""
    result = get_s3_key(
        inputs.prefix,
        inputs.data_interval_start,
        inputs.data_interval_end,
        inputs.batch_export_model,
        inputs.file_format,
        inputs.compression,
        use_new_file_naming_scheme=inputs.max_file_size_mb is not None,
    )
    assert result == expected
