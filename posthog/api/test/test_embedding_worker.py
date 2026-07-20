from datetime import UTC, datetime

from unittest.mock import MagicMock, patch

from posthog.api.embedding_worker import DocumentKey, get_recently_seen_documents


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
        # Same document_id as `seen`, different product — must resolve independently.
        other_product = _doc("abc", product="error_tracking")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
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
        }
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
