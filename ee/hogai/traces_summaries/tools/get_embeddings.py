import os
import json
import asyncio

import httpx
import numpy as np
import jmespath
import structlog
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_fixed, wait_random

logger = structlog.get_logger(__name__)

EMBEDDINGS_API_URL = "https://api.openai.com/v1/embeddings"
EMBEDDINGS_MODEL = "text-embedding-3-large"
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
async def get_embeddings(client: httpx.AsyncClient, embeddings_input: list[str], label: str = "") -> list[list[float]]:
    input_data = {"input": embeddings_input, "model": EMBEDDINGS_MODEL}
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
        message = (
            f"Couldn't get embeddings ({embeddings_input}, {label}), no embeddings returned ({response}). Retrying."
        )
        logger.exception(message)
        raise RetryableException(message)
    if len(embeddings) != len(embeddings_input):
        message = (
            f"Got {len(embeddings)} embeddings for {len(embeddings_input)} "
            f"inputs ({embeddings_input}, {label}). Retrying."
        )
        logger.exception(message)
        raise RetryableException(message)
    return embeddings


# TODO: Remove after testing
if __name__ == "__main__":
    waka = asyncio.run(get_embeddings(client=httpx.AsyncClient(), embeddings_input=["Hello, world!"]))
    with open("waka.json", "w") as f:
        json.dump(waka, f)
    waka_np = np.array(waka)
    np.save("waka.npy", waka_np)
