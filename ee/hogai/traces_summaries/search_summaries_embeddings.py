import json
import asyncio
from pathlib import Path

import httpx
import numpy as np
import structlog
from clusterize_kmeans import cosine_similarity
from tools.get_embeddings import get_embeddings

logger = structlog.get_logger(__name__)


class EmbeddingSearcher:
    @classmethod
    def find_top_similar_documents(
        cls,
        search_request_embedding_np: np.ndarray,
        trace_id_to_embeddings_mapping: dict[str, np.ndarray],
        trace_ids_to_summaries_mapping: dict[str, str],
        top: int,
    ) -> list[dict[str, str]]:
        # Calculate cosine distance between search request embedding and all document embeddings
        cosine_distances = []
        for trace_id, document_embedding in trace_id_to_embeddings_mapping.items():
            similarity = cosine_similarity(search_request_embedding_np, document_embedding)
            cosine_distances.append((trace_id, similarity))
        # Find top 5 traces with the smallest cosine distance
        top_5_similar_trace_ids = sorted(cosine_distances, key=lambda x: x[1], reverse=True)[:top]
        # Load documents from the 5 traces
        top_5_similar_summaries = [
            {"trace_id": trace_id, "trace_summary": trace_ids_to_summaries_mapping[trace_id]}
            for trace_id, _ in top_5_similar_trace_ids
        ]
        return top_5_similar_summaries


async def get_embeddings_for_search_request(search_request_str: str) -> list[float]:
    client = httpx.AsyncClient()
    embeddings = await get_embeddings(
        client=client, embeddings_input=[search_request_str], label="search_request_embedding"
    )
    # It's a single embedding, so we can return it directly
    return embeddings[0]


if __name__ == "__main__":
    base_output_dir_path = Path("/Users/woutut/Documents/Code/posthog/playground/traces-summarization/output/")
    # Iterate over directories to find npy files with embeddings
    traces_dirs = list(base_output_dir_path.iterdir())
    # Load summaries to trace IDs mapping and reverse
    summaries_to_trace_ids_mapping_file_path = "/Users/woutut/Documents/Code/posthog/playground/traces-summarization/groups/summaries_to_trace_ids_mapping_25.json"
    with open(summaries_to_trace_ids_mapping_file_path) as f:
        summaries_to_trace_ids_mapping = json.load(f)
    input_trace_ids_to_summaries_mapping = {v: k for k, v in summaries_to_trace_ids_mapping.items()}
    # Prepare mapping
    input_trace_id_to_embeddings_mapping: dict[str, np.ndarray] = {}
    # Generate summaries for stringified traces
    for dir_path in traces_dirs:
        if not dir_path.is_dir():
            continue
        trace_id = dir_path.name
        # Load embeddings
        # playground/traces-summarization/output/6e4c8620-1a34-4d4d-948a-515062b5b941/6e4c8620-1a34-4d4d-948a-515062b5b941_summary_embeddings.npy
        embeddings_file_name = f"{trace_id}_summary_embeddings.npy"
        embeddings_file_path = dir_path / embeddings_file_name
        if not embeddings_file_path.exists():
            # TODO: Add proper check, skipping for simplicity now
            continue
        with open(embeddings_file_path, "rb") as f:
            embeddings_np = np.load(f, allow_pickle=True)
        # Each npy file contains a single embedding, so extract it (convert from (1, 3072) to (3072,))
        embedding = embeddings_np[0] if embeddings_np.ndim > 1 else embeddings_np
        # Add to mapping
        input_trace_id_to_embeddings_mapping[trace_id] = embedding
    # Generate embedding for the search request
    input_search_request_str = "Google Tag Manager"
    input_search_request_embedding = asyncio.run(
        get_embeddings_for_search_request(search_request_str=input_search_request_str)
    )
    input_search_request_embedding_np = np.array(input_search_request_embedding)
    similar_documents = EmbeddingSearcher.find_top_similar_documents(
        search_request_embedding_np=input_search_request_embedding_np,
        trace_id_to_embeddings_mapping=input_trace_id_to_embeddings_mapping,
        trace_ids_to_summaries_mapping=input_trace_ids_to_summaries_mapping,
        top=5,
    )
    logger.info(f"Top 5 similar traces to the search request ({input_search_request_str}): {similar_documents}")
