from unittest.mock import MagicMock, patch

from posthog.api.embedding_worker import emit_embedding_request
from posthog.kafka_client.topics import KAFKA_DOCUMENT_EMBEDDINGS_INPUT_TOPIC


def _valid_model() -> str:
    from products.error_tracking.backend.indexed_embedding import EMBEDDING_TABLES

    return next(iter(EMBEDDING_TABLES)).model_name


@patch("posthog.api.embedding_worker.get_producer")
def test_emit_embedding_request_keys_by_document_id(mock_get_producer: MagicMock) -> None:
    producer = MagicMock()
    mock_get_producer.return_value = producer

    emit_embedding_request(
        content="hello",
        team_id=1,
        product="signals",
        document_type="signal",
        rendering="full",
        document_id="doc-123",
        models=[_valid_model()],
    )

    producer.produce.assert_called_once()
    kwargs = producer.produce.call_args.kwargs
    assert kwargs["key"] == "doc-123"
    assert kwargs["topic"] == KAFKA_DOCUMENT_EMBEDDINGS_INPUT_TOPIC
    assert kwargs["data"]["document_id"] == "doc-123"
