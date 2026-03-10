from collections.abc import Generator
from typing import cast

from django.conf import settings

from azure.ai.inference import EmbeddingsClient
from azure.ai.inference.aio import EmbeddingsClient as EmbeddingsClientAsync
from azure.core.credentials import AzureKeyCredential


def _validate_azure_config() -> tuple[str, str]:
    endpoint = str(settings.AZURE_INFERENCE_ENDPOINT).strip()
    credential = str(settings.AZURE_INFERENCE_CREDENTIAL).strip()
    if not endpoint:
        raise ValueError(
            "AZURE_INFERENCE_ENDPOINT is not configured. The Azure embeddings client requires a valid endpoint URL."
        )
    if not credential:
        raise ValueError(
            "AZURE_INFERENCE_CREDENTIAL is not configured. The Azure embeddings client requires a valid API key."
        )
    return endpoint, credential


def get_azure_embeddings_client() -> EmbeddingsClient:
    endpoint, credential = _validate_azure_config()
    return EmbeddingsClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(credential),
    )


def get_async_azure_embeddings_client() -> EmbeddingsClientAsync:
    endpoint, credential = _validate_azure_config()
    return EmbeddingsClientAsync(
        endpoint=endpoint,
        credential=AzureKeyCredential(credential),
    )


async def aembed_documents(client: EmbeddingsClientAsync, texts: list[str]) -> Generator[list[float], None, None]:
    """Embed documents for storing in a vector database."""
    response = await client.embed(
        input=texts,
        encoding_format="float",
        model="embed-v-4-0",
        input_type="document",
    )
    if not response.data:
        raise ValueError("No embeddings returned")
    return (cast(list[float], res.embedding) for res in response.data)


def embed_search_query(client: EmbeddingsClient, text: str) -> list[float]:
    """Embed a search query for semantic search by stored documents."""
    response = client.embed(
        input=[text],
        encoding_format="float",
        model="embed-v-4-0",
        input_type="query",
    )
    if not response.data:
        raise ValueError("No embeddings returned")
    return cast(list[float], response.data[0].embedding)
