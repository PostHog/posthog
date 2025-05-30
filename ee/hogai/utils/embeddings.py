from collections.abc import Generator
from typing import cast

from azure.ai.projects import AIProjectClient
from azure.ai.projects.aio import AIProjectClient as AsyncAIProjectClient
from azure.core.credentials import AzureKeyCredential
from django.conf import settings


def get_azure_client() -> AIProjectClient:
    return AIProjectClient(
        endpoint=settings.AZURE_INFERENCE_ENDPOINT,
        credential=AzureKeyCredential(settings.AZURE_INFERENCE_CREDENTIAL),
    )


def get_async_azure_client() -> AsyncAIProjectClient:
    return AsyncAIProjectClient(
        endpoint=settings.AZURE_INFERENCE_ENDPOINT,
        credential=AzureKeyCredential(settings.AZURE_INFERENCE_CREDENTIAL),
    )


async def aembed_documents(client: AsyncAIProjectClient, texts: list[str]) -> Generator[list[float], None, None]:
    """Embed documents for storing in a vector database."""
    embeddings = client.inference.get_embeddings_client()
    response = await embeddings.embed(
        input=texts,
        encoding_format="float",
        model="embed-v-4-0",
        input_type="document",
    )
    if not response.data:
        raise ValueError("No embeddings returned")
    return (cast(list[float], res.embedding) for res in response.data)


def embed_search_query(client: AIProjectClient, text: str) -> list[float]:
    """Embed a search query for semantic search by stored documents."""
    embeddings = client.inference.get_embeddings_client()
    response = embeddings.embed(
        input=[text],
        encoding_format="float",
        model="embed-v-4-0",
        input_type="query",
    )
    if not response.data:
        raise ValueError("No embeddings returned")
    return cast(list[float], response.data[0].embedding)
