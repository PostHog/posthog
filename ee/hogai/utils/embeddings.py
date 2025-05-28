import cohere


def get_async_cohere_client() -> cohere.AsyncClientV2:
    return cohere.AsyncClientV2()


def get_cohere_client() -> cohere.ClientV2:
    return cohere.ClientV2()


async def aembed_documents(client: cohere.AsyncClientV2, texts: list[str]) -> list[list[float]]:
    """Embed documents for storing in a vector database."""
    response = await client.embed(
        texts=texts,
        model="embed-v4.0",
        input_type="search_document",
        embedding_types=["float"],
    )
    if not response.embeddings.float_:
        raise ValueError("No embeddings returned")
    return response.embeddings.float_


def embed_search_query(client: cohere.ClientV2, text: str) -> list[float]:
    """Embed a search query for semantic search by stored documents."""
    response = client.embed(
        texts=[text],
        model="embed-v4.0",
        input_type="search_query",
        embedding_types=["float"],
    )
    if not response.embeddings.float_ or not response.embeddings.float_:
        raise ValueError("No embeddings returned")
    return response.embeddings.float_[0]
