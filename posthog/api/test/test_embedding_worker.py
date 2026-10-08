from datetime import UTC, datetime

import pytest
from unittest.mock import MagicMock, patch

import httpx

from posthog.api.embedding_worker import DocumentKey, _raise_for_embedding_response, get_recently_seen_documents


def _doc(document_id: str, product: str = "signals") -> DocumentKey:
    return DocumentKey(
        product=product,
        document_type="signal",
        rendering="plain",
        document_id=document_id,
    )


class TestRecentlySeenLookup:
    @patch("posthog.api.embedding_worker.internal_requests")
    def test_maps_each_document_to_its_emit_time_keyed_by_full_identity(self, mock_requests):
        seen = _doc("abc")
        unseen = _doc("def")
        other_product = _doc("abc", product="error_tracking")

        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "product": "signals",
                "document_type": "signal",
                "rendering": "plain",
                "document_id": "abc",
                "emitted_at": "2026-06-26T12:00:00+00:00",
            },
            {
                "product": "signals",
                "document_type": "signal",
                "rendering": "plain",
                "document_id": "def",
                "emitted_at": None,
            },
            {
                "product": "error_tracking",
                "document_type": "signal",
                "rendering": "plain",
                "document_id": "abc",
                "emitted_at": None,
            },
        ]
        mock_requests.post.return_value = mock_response

        results = get_recently_seen_documents([seen, unseen, other_product], team_id=7)

        assert results[seen] == datetime(2026, 6, 26, 12, 0, 0, tzinfo=UTC)
        assert results[unseen] is None
        assert results[other_product] is None

        _, kwargs = mock_requests.post.call_args
        assert kwargs["json"]["team_id"] == 7
        assert {
            "product": "error_tracking",
            "document_type": "signal",
            "rendering": "plain",
            "document_id": "abc",
        } in kwargs["json"]["documents"]
        assert kwargs["timeout"] == 30.0

    @patch("posthog.api.embedding_worker.internal_requests")
    def test_empty_input_makes_no_request(self, mock_requests):
        assert get_recently_seen_documents([], team_id=1) == {}
        mock_requests.post.assert_not_called()


class TestRaiseForEmbeddingResponse:
    def test_bodyless_403_explains_the_ai_opt_in_gate(self):
        # The worker sends a bare status with no body, so a helper that looked for
        # explanatory text in the response would never recognise the opt-in gate.
        response = MagicMock(status_code=403, text="")

        with pytest.raises(httpx.HTTPStatusError, match="not opted into AI data processing"):
            _raise_for_embedding_response(response)

        response.raise_for_status.assert_not_called()

    def test_other_errors_fall_through_to_raise_for_status(self):
        response = MagicMock(status_code=500, text="")

        _raise_for_embedding_response(response)

        response.raise_for_status.assert_called_once()

    def test_success_is_passed_through(self):
        response = MagicMock(status_code=200, text="")

        _raise_for_embedding_response(response)

        response.raise_for_status.assert_called_once()
