import re
import asyncio
import difflib
from copy import copy
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np
import structlog
from rich.console import Console
from tools.get_embeddings import get_embeddings

console = Console()

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


def _log_diff(trace_id: str, original_summary: str, summary: str) -> None:
    logger.info(
        f"Summary cleaned up for trace {trace_id}",
        changes_made=original_summary != summary,
        old_length=len(original_summary),
        new_length=len(summary),
    )
    logger.info(f"Original summary:\n{original_summary}")
    logger.info(f"Cleaned summary:\n{summary}")
    # Character-level diff for precise changes
    console.print("[bold]Changes:[/bold]")
    matcher = difflib.SequenceMatcher(None, original_summary, summary)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "delete":
            console.print(f"[red]Removed: '{original_summary[i1:i2]}'[/red]")
        elif tag == "insert":
            console.print(f"[green]Added: '{summary[j1:j2]}'[/green]")
        elif tag == "replace":
            console.print(f"[red]Removed: '{original_summary[i1:i2]}'[/red]")
            console.print(f"[green]Added: '{summary[j1:j2]}'[/green]")
    console.print("=" * 50 + "\n")


def _clean_up_summary_before_embedding(trace_id: str, summary: str, log_diff: bool = False) -> str:
    """Remove repetitive phrases and excessive formatting to make embeddings more accurate."""
    original_summary = copy(summary)
    # Remove parts that don't add value
    no_value_parts = ["several", "during the interaction", "explicitly"]
    for part in no_value_parts:
        summary = summary.replace(part, " ")
    # Remove excessive prefixes
    excessive_prefixes = ["The user experienced"]
    for prefix in excessive_prefixes:
        while True:
            # Remove all occurrences
            prefix_index = summary.find(prefix)
            if prefix_index == -1:
                # Not found
                break
            # Remove prefix
            summary = summary[:prefix_index] + summary[prefix_index + len(prefix) :]
    # Remove narrative words (one word before comma at the start of the sentence)
    narrative_regex = r"(^|\n|\.\"\s|\.\s)([A-Z]\w+, )"
    summary = re.sub(narrative_regex, lambda m: m.group(1), summary)
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
    # Strip, just in case
    summary = summary.strip()
    # Replace the symbols after dot + space, newline + space, or start + space with uppercase if they are lowercase
    summary = re.sub(r"(\.\s|\n\s|\.\"\s|^)([a-z])", lambda m: m.group(1) + m.group(2).upper(), summary)
    if len(summary) / len(original_summary) <= 0.8:
        # Force log diff if drastic difference
        log_diff = True
    if summary == original_summary or not log_diff:
        return summary
    # Log differences, if any, whhen asked explicitly
    _log_diff(trace_id=trace_id, original_summary=original_summary, summary=summary)
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
        # Skip summaries without issues
        if summary.strip(".").strip(" ").lower() == "no issues found":
            continue
        _clean_up_summary_before_embedding(trace_id=trace_id, summary=summary, log_diff=False)
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
