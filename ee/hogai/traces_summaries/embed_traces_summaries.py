import asyncio
from copy import copy
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


def _clean_up_summary_before_embedding(summary: str) -> str:
    """Remove repetitive phrases and excessive formatting to make embeddings more accurate."""
    original_summary = copy(summary)
    # Remove words that don't add value
    no_value_words = ["several"]
    for word in no_value_words:
        summary = summary.replace(f" {word} ", " ")  # Ensure to replace full words only
    # Remove excessive prefixes
    excessive_prefixes = ["The user experienced"]
    for prefix in excessive_prefixes:
        while True:
            # Remove all occurrences
            prefix_index = summary.find(prefix)
            if prefix_index == -1:
                # Not found
                break
            # Make next symbol uppercase (assuming space after prefix)
            prefix_next_char_index = prefix_index + len(prefix) + 1
            if prefix_next_char_index < len(summary):  # Apply if within bounds
                summary = (
                    summary[:prefix_next_char_index]
                    + summary[prefix_next_char_index].upper()
                    + summary[prefix_next_char_index + 1 :]
                )
            # Remove prefix
            summary = summary[prefix_index + len(prefix) :]
    # Remove excessive formatting
    excessive_formatting = ["**"]
    for formatting in excessive_formatting:
        while True:
            # Remove all occurrences
            formatting_index = summary.find(formatting)
            if formatting_index == -1:
                break
            # Remove formatting
            summary = summary[:formatting_index] + summary[formatting_index + len(formatting) :]
    # Log differences, if any
    if summary != original_summary:
        logger.info("*" * 50)
        logger.info(f"Old summary: {original_summary}")
        logger.info(f"New summary: {summary}")
    return summary


if __name__ == "__main__":
    stringified_traces_dir_path = Path("/Users/woutut/Documents/Code/posthog/playground/traces-summarization/output/")
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
        _clean_up_summary_before_embedding(summary=summary)
        break
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
    # # Generate embeddings
    # asyncio.run(_process_embedding_tasks(tasks=tasks))
