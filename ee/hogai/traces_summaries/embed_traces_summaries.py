import asyncio
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np
import structlog
from tools.get_embeddings import get_embeddings

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class TraceSummaryEmbeddingTask:
    trace_id: str
    embeddings_input: list[str]
    embeddings_output_file_path: Path


async def _embed_summary(client: httpx.AsyncClient, task: TraceSummaryEmbeddingTask) -> None:
    """Embed summary and save to file."""
    summary_embeddings = await get_embeddings(
        client=client, embeddings_input=task.embeddings_input, label=task.trace_id
    )
    if not summary_embeddings:
        logger.error(f"No embeddings returned for trace {task.trace_id}")
        return
    summary_embeddings_np = np.array(summary_embeddings)
    np.save(task.embeddings_output_file_path, summary_embeddings_np)
    logger.info(f"Embedded summary for trace {task.trace_id}")


async def _process_embedding_tasks(tasks: list[TraceSummaryEmbeddingTask]) -> None:
    """Process embedding tasks in parallel."""
    limits = httpx.Limits(max_connections=20)
    client = httpx.AsyncClient(limits=limits)
    # Split into chunks of 1000 tasks for smoother/more predictable processing
    chunks = [tasks[i : i + 1000] for i in range(0, len(tasks), 1000)]
    for chunk in chunks:
        processing_tasks = [_embed_summary(client=client, task=task) for task in chunk]
        await asyncio.gather(*processing_tasks)


if __name__ == "__main__":
    stringified_traces_dir_path = Path("/Users/woutut/Documents/Code/posthog/playground/traces-summarization/output/")
    client = httpx.AsyncClient()
    # Iterate over directories in stringified_traces_dir_path
    traces_dirs = list(stringified_traces_dir_path.iterdir())
    tasks = []
    # Generate summaries for stringified traces
    for dir_path in traces_dirs:
        if not dir_path.is_dir():
            continue
        trace_id = dir_path.name
        # Get stringified trace summary
        summary_file_name = f"{trace_id}_summary.txt"
        summary_file_path = dir_path / summary_file_name
        if not summary_file_path.exists():
            raise ValueError(f"Summary file ({summary_file_path}) not found for trace {trace_id}")
        with open(summary_file_path) as f:
            summary = f.read()
        # Skip summaries without issues
        if summary.strip(".").strip(" ").lower() == "no issues found":
            continue
        # Check if embeddings file already exists
        summary_embeddings_file_path = dir_path / f"{trace_id}_summary_embeddings.npy"
        if summary_embeddings_file_path.exists():
            # Check that it's not empty
            with open(summary_embeddings_file_path, "rb") as f:
                summary_embeddings = np.load(f, allow_pickle=True)
            if not summary_embeddings.size:
                raise ValueError(
                    f"Summary embeddings file ({summary_embeddings_file_path}) is empty for trace {trace_id}"
                )
            # No need to process again
            continue
        # Prepare task
        task = TraceSummaryEmbeddingTask(
            trace_id=trace_id,
            embeddings_input=[summary],
            embeddings_output_file_path=summary_embeddings_file_path,
        )
        tasks.append(task)
    # Generate embeddings
    asyncio.run(_process_embedding_tasks(tasks=tasks))
