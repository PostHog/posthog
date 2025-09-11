from collections.abc import Generator
from typing import cast

from django.conf import settings

from azure.ai.inference import EmbeddingsClient
from azure.ai.inference.aio import EmbeddingsClient as EmbeddingsClientAsync
from azure.core.credentials import AzureKeyCredential


def get_azure_embeddings_client() -> EmbeddingsClient:
    return EmbeddingsClient(
        endpoint=settings.AZURE_INFERENCE_ENDPOINT,
        credential=AzureKeyCredential(settings.AZURE_INFERENCE_CREDENTIAL),
    )


def get_async_azure_embeddings_client() -> EmbeddingsClientAsync:
    return EmbeddingsClientAsync(
        endpoint=settings.AZURE_INFERENCE_ENDPOINT,
        credential=AzureKeyCredential(settings.AZURE_INFERENCE_CREDENTIAL),
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
