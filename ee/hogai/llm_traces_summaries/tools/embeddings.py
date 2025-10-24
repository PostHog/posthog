import os
import httpx
import jmespath
import structlog
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_fixed, wait_random

from posthog.schema import EmbeddingModelName

logger = structlog.get_logger(__name__)

EMBEDDINGS_API_URL = "https://api.openai.com/v1/embeddings"
EMBEDDINGS_API_KEY = os.getenv("OPENAI_API_KEY")


class RetryableException(Exception):
    pass


def failed_get_embeddings(
    retry_state: RetryCallState,
) -> None:
    logger.error(
        f"Couldn't get embedding with {retry_state.attempt_number} attemps ({round(retry_state.idle_for, 2)}s)."
    )
    return None


@retry(
    retry=retry_if_exception_type(RetryableException),
    stop=stop_after_attempt(5),
    wait=wait_fixed(1) + wait_random(0, 3),
    retry_error_callback=failed_get_embeddings,
)
async def get_embeddings(
    client: httpx.AsyncClient,
    embeddings_input: list[str],
    embedding_model_name: EmbeddingModelName = EmbeddingModelName.TEXT_EMBEDDING_3_LARGE_3072,
    label: str = "",
) -> list[list[float]]:
    input_data = {"input": embeddings_input, "model": embedding_model_name.value}
    try:
        raw_response = await client.post(
            url=EMBEDDINGS_API_URL,
            json=input_data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {EMBEDDINGS_API_KEY}",
            },
        )
        response = raw_response.json()
    except httpx.HTTPStatusError as err:
        message = f"Request error when getting embeddings: {err}"
        logger.exception(message)
        raise RetryableException(message)
    embeddings = jmespath.search("data[].embedding", response)
    if not embeddings:
        message = f"Couldn't get embeddings ({embeddings_input}, {label}) for model {embedding_model_name.value}, no embeddings returned ({response}). Retrying."
        logger.exception(message)
        raise RetryableException(message)
    if len(embeddings) != len(embeddings_input):
        message = (
            f"Got {len(embeddings)} embeddings for {len(embeddings_input)} "
            f"inputs ({embeddings_input}, {label}) for model {embedding_model_name.value}. Retrying."
        )
        logger.exception(message)
        raise RetryableException(message)
    return embeddings
