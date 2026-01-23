import json
from datetime import datetime

import pytest
from unittest.mock import MagicMock, patch

import polars as pl
import requests
from parameterized import parameterized

from posthog.dags.common.resources import ClayWebhookResource

from ee.billing.dags.job_switchers import (
    clickhouse_to_dataframe,
    compute_dataframe_hashes,
    dataframe_to_clay_payload,
    filter_changed_domains,
    get_prior_hashes_from_metadata,
)


class TestClickhouseToDataframe:
    @parameterized.expand(
        [
            (
                "single_row",
                [
                    (
                        "example.com",
                        ["user1@example.com", "user2@example.com"],
                        5,
                        datetime(2024, 1, 15, 10, 30),
                        datetime(2024, 6, 20, 14, 22),
                        ["Subject 1"],
                        ["mailbox full"],
                        ["org-123"],
                        ["Example Corp"],
                        [1704067200],
                        ["voluntary"],
                        ["customer_io_delivery"],
                    ),
                ],
                1,
                "example.com",
                5,
            ),
            (
                "multiple_rows",
                [
                    (
                        "a.com",
                        ["a@a.com"],
                        1,
                        None,
                        None,
                        [],
                        [],
                        [],
                        [],
                        [],
                        [],
                        [],
                    ),
                    (
                        "b.com",
                        ["b@b.com"],
                        2,
                        None,
                        None,
                        [],
                        [],
                        [],
                        [],
                        [],
                        [],
                        [],
                    ),
                ],
                2,
                "a.com",
                1,
            ),
        ]
    )
    def test_converts_results_to_dataframe(
        self, name: str, results: list, expected_len: int, expected_domain: str, expected_bounce_count: int
    ):
        df = clickhouse_to_dataframe(results)

        assert isinstance(df, pl.DataFrame)
        assert len(df) == expected_len
        assert df["email_domain"][0] == expected_domain
        assert df["bounce_count"][0] == expected_bounce_count

    def test_handles_empty_results(self):
        df = clickhouse_to_dataframe([])
        assert len(df) == 0


class TestComputeDataframeHashes:
    def test_computes_hash_for_each_row(self):
        df = pl.DataFrame(
            {
                "email_domain": ["a.com", "b.com"],
                "emails": [["x@a.com"], ["y@b.com"]],
                "bounce_count": [1, 2],
            }
        )

        df_with_hash = compute_dataframe_hashes(df)

        assert "data_hash" in df_with_hash.columns
        assert len(df_with_hash) == 2
        # Hashes should be 16 chars
        assert all(len(h) == 16 for h in df_with_hash["data_hash"])

    def test_same_data_produces_same_hash(self):
        df1 = pl.DataFrame({"email_domain": ["a.com"], "bounce_count": [1]})
        df2 = pl.DataFrame({"email_domain": ["a.com"], "bounce_count": [1]})

        h1 = compute_dataframe_hashes(df1)["data_hash"][0]
        h2 = compute_dataframe_hashes(df2)["data_hash"][0]

        assert h1 == h2

    def test_different_data_produces_different_hash(self):
        df1 = pl.DataFrame({"email_domain": ["a.com"], "bounce_count": [1]})
        df2 = pl.DataFrame({"email_domain": ["a.com"], "bounce_count": [2]})

        h1 = compute_dataframe_hashes(df1)["data_hash"][0]
        h2 = compute_dataframe_hashes(df2)["data_hash"][0]

        assert h1 != h2


class TestFilterChangedDomains:
    @parameterized.expand(
        [
            (
                "returns_all_when_no_prior_state",
                pl.DataFrame(
                    {
                        "email_domain": ["a.com", "b.com"],
                        "data_hash": ["hash1", "hash2"],
                    }
                ),
                {},
                2,
                ["a.com", "b.com"],
            ),
            (
                "filters_unchanged_domains",
                pl.DataFrame(
                    {
                        "email_domain": ["a.com", "b.com"],
                        "data_hash": ["hash1", "hash2"],
                    }
                ),
                {"a.com": "hash1"},
                1,
                ["b.com"],
            ),
            (
                "includes_changed_domains",
                pl.DataFrame(
                    {
                        "email_domain": ["a.com"],
                        "data_hash": ["new_hash"],
                    }
                ),
                {"a.com": "old_hash"},
                1,
                ["a.com"],
            ),
            (
                "filters_all_unchanged",
                pl.DataFrame(
                    {
                        "email_domain": ["a.com", "b.com"],
                        "data_hash": ["hash1", "hash2"],
                    }
                ),
                {"a.com": "hash1", "b.com": "hash2"},
                0,
                [],
            ),
        ]
    )
    def test_filter_changed_domains(
        self,
        name: str,
        current: pl.DataFrame,
        prior_hashes: dict,
        expected_len: int,
        expected_domains: list,
    ):
        filtered = filter_changed_domains(current, prior_hashes)

        assert len(filtered) == expected_len
        assert filtered["email_domain"].to_list() == expected_domains


class TestDataframeToClayPayload:
    def test_converts_to_list_of_dicts(self):
        df = pl.DataFrame(
            {
                "email_domain": ["example.com"],
                "emails": [["user@example.com"]],
                "bounce_count": [5],
                "first_bounce_at": [datetime(2024, 1, 15)],
                "last_bounce_at": [None],
                "subjects": [["Test subject"]],
                "bounce_reasons": [["mailbox full"]],
                "organization_ids": [["org-1"]],
                "organization_names": [["Example Corp"]],
                "removal_timestamps": [[1704067200]],
                "removal_types": [["voluntary"]],
                "source_type": [["customer_io"]],
            }
        )

        payload = dataframe_to_clay_payload(df)

        assert isinstance(payload, list)
        assert len(payload) == 1
        assert payload[0]["domain"] == "example.com"
        assert payload[0]["emails"] == ["user@example.com"]
        assert payload[0]["first_bounce_at"] == "2024-01-15T00:00:00"
        assert payload[0]["last_bounce_at"] is None
        assert payload[0]["bounce_count"] == 5
        assert payload[0]["organization_names"] == ["Example Corp"]

    def test_handles_null_arrays(self):
        df = pl.DataFrame(
            {
                "email_domain": ["test.com"],
                "emails": [None],
                "bounce_count": [0],
                "first_bounce_at": [None],
                "last_bounce_at": [None],
                "subjects": [None],
                "bounce_reasons": [None],
                "organization_ids": [None],
                "organization_names": [None],
                "removal_timestamps": [None],
                "removal_types": [None],
                "source_type": [None],
            }
        )

        payload = dataframe_to_clay_payload(df)

        assert payload[0]["emails"] == []
        assert payload[0]["bounce_reasons"] == []


class TestGetPriorHashesFromMetadata:
    def test_returns_empty_dict_when_no_prior_materialization(self):
        mock_context = MagicMock()
        mock_context.instance.get_latest_materialization_event.return_value = None

        result = get_prior_hashes_from_metadata(mock_context)

        assert result == {}

    def test_extracts_hashes_from_metadata(self):
        mock_context = MagicMock()
        mock_event = MagicMock()
        mock_metadata = MagicMock()
        mock_metadata.value = {"a.com": "hash1", "b.com": "hash2"}
        mock_event.asset_materialization.metadata = {"domain_hashes": mock_metadata}
        mock_context.instance.get_latest_materialization_event.return_value = mock_event

        with patch("ee.billing.dags.job_switchers.JsonMetadataValue", MagicMock):
            # Mock isinstance to return True for our mock metadata
            with patch("ee.billing.dags.job_switchers.isinstance", return_value=True):
                result = get_prior_hashes_from_metadata(mock_context)

        assert result == {"a.com": "hash1", "b.com": "hash2"}


class TestClayWebhookResource:
    def test_send_makes_post_request(self):
        with patch("posthog.dags.common.resources.requests.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value.__enter__.return_value = mock_session
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_session.post.return_value = mock_response

            resource = ClayWebhookResource(
                webhook_url="https://api.clay.com/webhook/123",
                api_key="test-key",
            )
            data = [{"domain": "example.com", "emails": []}]

            response = resource.send(data)

            mock_session.post.assert_called_once()
            call_args = mock_session.post.call_args
            assert call_args.kwargs["json"] == data
            assert call_args.kwargs["headers"]["x-clay-webhook-auth"] == "test-key"
            assert call_args.kwargs["headers"]["Content-Type"] == "application/json"
            assert response.status_code == 200

    def test_send_raises_on_error_status(self):
        with patch("posthog.dags.common.resources.requests.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value.__enter__.return_value = mock_session
            mock_response = MagicMock()
            mock_response.raise_for_status.side_effect = Exception("HTTP 500")
            mock_session.post.return_value = mock_response

            resource = ClayWebhookResource(
                webhook_url="https://api.clay.com/webhook/123",
                api_key="test-key",
            )

            with pytest.raises(Exception):
                resource.send([{"domain": "example.com"}])

    def test_send_batched_empty_data(self):
        with patch("posthog.dags.common.resources.requests.Session") as mock_session_class:
            resource = ClayWebhookResource(
                webhook_url="https://api.clay.com/webhook/123",
                api_key="test-key",
            )

            responses = resource.send_batched([])

            assert responses == []
            mock_session_class.assert_not_called()

    def test_send_batched_single_batch(self):
        with patch("posthog.dags.common.resources.requests.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value.__enter__.return_value = mock_session
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_session.post.return_value = mock_response

            resource = ClayWebhookResource(
                webhook_url="https://api.clay.com/webhook/123",
                api_key="test-key",
                max_records_per_batch=100,  # High limit to ensure single batch
            )
            data = [{"domain": f"{i}.com"} for i in range(50)]

            responses = resource.send_batched(data)

            assert len(responses) == 1
            mock_session.post.assert_called_once()
            assert mock_session.post.call_args.kwargs["json"] == data

    def test_send_batched_multiple_batches(self):
        with patch("posthog.dags.common.resources.requests.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value.__enter__.return_value = mock_session
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_session.post.return_value = mock_response

            max_bytes = 100
            resource = ClayWebhookResource(
                webhook_url="https://api.clay.com/webhook/123",
                api_key="test-key",
                max_batch_bytes=max_bytes,
                max_records_per_batch=100,  # High limit so bytes constraint wins
            )
            data = [{"domain": f"{i}.com"} for i in range(12)]

            responses = resource.send_batched(data)

            assert len(responses) == 3
            assert mock_session.post.call_count == 3

            # Verify each batch is under the size limit
            for call in mock_session.post.call_args_list:
                batch = call.kwargs["json"]
                batch_size = len(json.dumps(batch, default=str).encode("utf-8"))
                assert batch_size <= max_bytes, f"Batch size {batch_size} exceeds limit {max_bytes}"

    def test_retry_on_transient_failure_recovers(self):
        """Transient 503 that recovers after retry should succeed."""
        with patch("posthog.dags.common.resources.requests.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value.__enter__.return_value = mock_session

            # First two calls fail with 503, third succeeds
            fail_response = MagicMock()
            fail_response.status_code = 503
            error = requests.exceptions.HTTPError("503 Service Unavailable", response=fail_response)
            fail_response.raise_for_status.side_effect = error

            success_response = MagicMock()
            success_response.status_code = 200
            success_response.raise_for_status.return_value = None

            mock_session.post.side_effect = [fail_response, fail_response, success_response]

            resource = ClayWebhookResource(
                webhook_url="https://api.clay.com/webhook/123",
                api_key="test-key",
                max_retries=3,
            )

            response = resource.send([{"domain": "example.com"}])

            assert response.status_code == 200
            assert mock_session.post.call_count == 3

    def test_retry_exhausted_raises_error(self):
        """Persistent failures should exhaust retries and raise."""
        with patch("posthog.dags.common.resources.requests.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value.__enter__.return_value = mock_session

            # Always fail with 503
            fail_response = MagicMock()
            fail_response.status_code = 503
            error = requests.exceptions.HTTPError("503 Service Unavailable", response=fail_response)
            fail_response.raise_for_status.side_effect = error
            mock_session.post.return_value = fail_response

            resource = ClayWebhookResource(
                webhook_url="https://api.clay.com/webhook/123",
                api_key="test-key",
                max_retries=2,
            )

            with pytest.raises(requests.exceptions.HTTPError):
                resource.send([{"domain": "example.com"}])

            # Initial attempt + 2 retries = 3 total
            assert mock_session.post.call_count == 3

    def test_non_retryable_error_not_retried(self):
        """400 Bad Request should not be retried."""
        with patch("posthog.dags.common.resources.requests.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value.__enter__.return_value = mock_session

            fail_response = MagicMock()
            fail_response.status_code = 400
            error = requests.exceptions.HTTPError("400 Bad Request", response=fail_response)
            fail_response.raise_for_status.side_effect = error
            mock_session.post.return_value = fail_response

            resource = ClayWebhookResource(
                webhook_url="https://api.clay.com/webhook/123",
                api_key="test-key",
                max_retries=3,
            )

            with pytest.raises(requests.exceptions.HTTPError):
                resource.send([{"domain": "example.com"}])

            # Should only attempt once since 400 is not retryable
            assert mock_session.post.call_count == 1

    def test_send_batched_skips_single_oversized_record(self):
        """A single record that exceeds max_batch_bytes should be skipped."""
        with patch("posthog.dags.common.resources.requests.Session") as mock_session_class:
            resource = ClayWebhookResource(
                webhook_url="https://api.clay.com/webhook/123",
                api_key="test-key",
                max_batch_bytes=50,  # Very small limit
            )
            oversized_record = {"domain": "example.com", "data": "x" * 100}

            responses = resource.send_batched([oversized_record])

            # Should return empty list since the only record was skipped
            assert responses == []
            mock_session_class.return_value.__enter__.return_value.post.assert_not_called()

    def test_send_batched_skips_oversized_record_sends_others(self):
        """An oversized record should be skipped while other records are sent."""
        with patch("posthog.dags.common.resources.requests.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value.__enter__.return_value = mock_session
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_session.post.return_value = mock_response

            resource = ClayWebhookResource(
                webhook_url="https://api.clay.com/webhook/123",
                api_key="test-key",
                max_batch_bytes=100,
                max_records_per_batch=100,  # High limit so bytes constraint wins
            )
            small_record = {"d": "a.com"}
            oversized_record = {"domain": "example.com", "data": "x" * 200}

            responses = resource.send_batched([small_record, oversized_record, small_record])

            # Should send only the small records, skipping the oversized one
            assert len(responses) == 1
            sent_data = mock_session.post.call_args.kwargs["json"]
            assert len(sent_data) == 2
            assert all(r["d"] == "a.com" for r in sent_data)

    def test_send_batched_truncates_oversized_array_fields(self):
        """Records with oversized array fields should be truncated to fit."""
        with patch("posthog.dags.common.resources.requests.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value.__enter__.return_value = mock_session
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_session.post.return_value = mock_response

            resource = ClayWebhookResource(
                webhook_url="https://api.clay.com/webhook/123",
                api_key="test-key",
                max_batch_bytes=500,
            )
            # Create a record with a large array in a truncatable field
            oversized_record = {
                "domain": "example.com",
                "emails": [f"user{i}@example.com" for i in range(100)],
            }
            original_size = len(json.dumps([oversized_record]).encode("utf-8"))
            assert original_size > 500  # Verify it's actually oversized

            responses = resource.send_batched([oversized_record])

            # Should succeed without raising
            assert len(responses) == 1
            # The sent record should have truncated emails
            sent_data = mock_session.post.call_args.kwargs["json"]
            assert len(sent_data) == 1
            assert len(sent_data[0]["emails"]) < 100  # Should be truncated
            # Verify it fits in the limit
            sent_size = len(json.dumps(sent_data).encode("utf-8"))
            assert sent_size <= 500

    def test_send_batched_invokes_callback_per_batch(self):
        """on_batch_sent callback should be called for each successfully sent batch."""
        with patch("posthog.dags.common.resources.requests.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value.__enter__.return_value = mock_session
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_session.post.return_value = mock_response

            resource = ClayWebhookResource(
                webhook_url="https://api.clay.com/webhook/123",
                api_key="test-key",
                max_records_per_batch=2,
                max_batch_bytes=100_000,  # High limit so record count wins
            )
            data = [{"domain": f"{i}.com"} for i in range(5)]

            callback_calls: list[list[dict]] = []
            responses = resource.send_batched(data, on_batch_sent=lambda batch: callback_calls.append(batch))

            # Should have 3 batches: 2 + 2 + 1
            assert len(responses) == 3
            assert len(callback_calls) == 3
            # Verify callback received the actual batch data
            assert len(callback_calls[0]) == 2
            assert len(callback_calls[1]) == 2
            assert len(callback_calls[2]) == 1
            # Verify the data matches
            assert callback_calls[0][0]["domain"] == "0.com"
            assert callback_calls[2][0]["domain"] == "4.com"


class TestClayWebhookResourceCreateBatches:
    """Tests for the create_batches method."""

    def test_create_batches_empty_data(self):
        resource = ClayWebhookResource(
            webhook_url="https://api.clay.com/webhook/123",
            api_key="test-key",
        )

        batches = resource.create_batches([])

        assert batches == []

    def test_create_batches_respects_record_count_limit(self):
        resource = ClayWebhookResource(
            webhook_url="https://api.clay.com/webhook/123",
            api_key="test-key",
            max_records_per_batch=3,
            max_batch_bytes=100_000,  # High limit so record count wins
        )
        data = [{"domain": f"{i}.com"} for i in range(10)]

        batches = resource.create_batches(data)

        assert len(batches) == 4  # 3 + 3 + 3 + 1
        assert len(batches[0]) == 3
        assert len(batches[1]) == 3
        assert len(batches[2]) == 3
        assert len(batches[3]) == 1

    def test_create_batches_respects_byte_limit(self):
        resource = ClayWebhookResource(
            webhook_url="https://api.clay.com/webhook/123",
            api_key="test-key",
            max_records_per_batch=100,  # High limit so bytes constraint wins
            max_batch_bytes=100,
        )
        data = [{"domain": f"{i}.com"} for i in range(10)]

        batches = resource.create_batches(data)

        # Verify each batch is under the byte limit
        for batch in batches:
            batch_size = len(json.dumps(batch, default=str).encode("utf-8"))
            assert batch_size <= 100

    def test_create_batches_truncates_oversized_records(self):
        resource = ClayWebhookResource(
            webhook_url="https://api.clay.com/webhook/123",
            api_key="test-key",
            max_batch_bytes=500,
            max_records_per_batch=10,
        )
        # Create a record with a large array in a truncatable field
        oversized_record = {
            "domain": "example.com",
            "emails": [f"user{i}@example.com" for i in range(100)],
        }
        original_size = len(json.dumps([oversized_record]).encode("utf-8"))
        assert original_size > 500  # Verify it's actually oversized

        batches = resource.create_batches([oversized_record])

        assert len(batches) == 1
        assert len(batches[0]) == 1
        # The record should have truncated emails
        assert len(batches[0][0]["emails"]) < 100
        # Verify it fits in the limit
        batch_size = len(json.dumps(batches[0]).encode("utf-8"))
        assert batch_size <= 500

    def test_create_batches_skips_untruncatable_oversized_records(self):
        resource = ClayWebhookResource(
            webhook_url="https://api.clay.com/webhook/123",
            api_key="test-key",
            max_batch_bytes=50,  # Very small limit
            max_records_per_batch=10,
        )
        # Record that can't be truncated to fit (no truncatable array fields)
        oversized_record = {"domain": "example.com", "data": "x" * 100}

        batches = resource.create_batches([oversized_record])

        assert batches == []  # Record was skipped

    def test_create_batches_mixed_sizes(self):
        resource = ClayWebhookResource(
            webhook_url="https://api.clay.com/webhook/123",
            api_key="test-key",
            max_batch_bytes=100,
            max_records_per_batch=10,
        )
        small_record = {"d": "a.com"}
        oversized_record = {"domain": "example.com", "data": "x" * 200}

        batches = resource.create_batches([small_record, oversized_record, small_record])

        # Only small records should be included
        assert len(batches) == 1
        assert len(batches[0]) == 2
        assert all(r["d"] == "a.com" for r in batches[0])

    @parameterized.expand(
        [
            ("single_record_fits", 1, 10, 10000, 1, [1]),
            ("exact_batch_boundary", 10, 10, 10000, 1, [10]),
            ("one_over_boundary", 11, 10, 10000, 2, [10, 1]),
            ("many_small_batches", 25, 3, 10000, 9, [3, 3, 3, 3, 3, 3, 3, 3, 1]),
        ]
    )
    def test_create_batches_boundary_conditions(
        self,
        name: str,
        num_records: int,
        max_per_batch: int,
        max_bytes: int,
        expected_batch_count: int,
        expected_batch_sizes: list[int],
    ):
        resource = ClayWebhookResource(
            webhook_url="https://api.clay.com/webhook/123",
            api_key="test-key",
            max_records_per_batch=max_per_batch,
            max_batch_bytes=max_bytes,
        )
        data = [{"domain": f"{i}.com"} for i in range(num_records)]

        batches = resource.create_batches(data)

        assert len(batches) == expected_batch_count
        assert [len(b) for b in batches] == expected_batch_sizes
