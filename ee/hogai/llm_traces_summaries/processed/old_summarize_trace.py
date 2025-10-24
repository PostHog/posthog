import os
import re
import time
import difflib
from copy import copy
from pathlib import Path

import numpy as np
import tiktoken
import structlog
from google import genai
from google.genai.types import GenerateContentConfig
from rich.console import Console

logger = structlog.get_logger(__name__)

FULL_TRACE_SUMMARY_PROMPT = """
- Analyze this conversation between the user and the PostHog AI assistant
- List all pain points, frustrations, and feature limitations the user experienced.
- IMPORTANT: Count only specific issues the user experienced when interacting with the assistant, don't guess or suggest.
- If no issues - return only "No issues found" text, without any additional comments.
- If issues found - provide output as plain English text in a maximum of 10 sentences, while highlighting all the crucial parts.

```
{trace_messages_str}
```
"""

console = Console()


class TraceSummarizer:
    def __init__(self, model_id: str):
        self.model_id = model_id
        self.client = self._prepare_client()

    @staticmethod
    def _prepare_client() -> genai.Client:
        api_key = os.getenv("GEMINI_API_KEY")
        return genai.Client(api_key=api_key)

    def generate_trace_summary(self, trace_messages_str: str) -> str:
        message = FULL_TRACE_SUMMARY_PROMPT.format(trace_messages_str=trace_messages_str)
        config_kwargs = {"temperature": 0}  # Not using any system prompt for saving tokens, as should be good enough
        response = self.client.models.generate_content(
            model=self.model_id, contents=message, config=GenerateContentConfig(**config_kwargs)
        )
        response_text = response.text
        if "No issues found" in response_text and response_text != "No issues found":
            logger.info(f"Original 'no issues' text: {response_text}")
            # Ensure to avoid additional comments when no issues found
            return "No issues found"
        return response_text


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
    summarizer = TraceSummarizer(
        model_id="gemini-2.5-flash-lite-preview-09-2025",
    )
    # Iterate over directories in stringified_traces_dir_path
    traces_dirs = list(stringified_traces_dir_path.iterdir())
    traces_processed_count = 0
    # Calculate token count
    token_encoder = tiktoken.encoding_for_model("gpt-4o")
    token_counts: list[int] = []
    # Calculate response times
    response_times_ms: list[int] = []
    # Generate summaries for stringified traces
    for dir_path in traces_dirs:
        if not dir_path.is_dir():
            continue
        trace_id = dir_path.name
        # Get stringified trace
        stringified_messages_file_name = f"{trace_id}_stringified_messages.txt"
        stringified_messages_file_path = dir_path / stringified_messages_file_name
        if not stringified_messages_file_path.exists():
            raise ValueError(
                f"Stringified messages file ({stringified_messages_file_path}) not found for trace {trace_id}"
            )
        # Load stringified trace
        with open(stringified_messages_file_path) as f:
            trace_messages_str = f.read()
        # Check if summary file already exists
        summary_file_path = dir_path / f"{trace_id}_summary.txt"
        if summary_file_path.exists():
            # Check that it's not empty
            with open(summary_file_path) as f:
                summary = f.read()
                if not summary:
                    raise ValueError(f"Summary file ({summary_file_path}) is empty for trace {trace_id}")
            token_counts.append(len(token_encoder.encode(summary)))
            # Clean up the summary before embedding
            unfiltered_summary = copy(summary)
            cleaned_up_summary = _clean_up_summary_before_embedding(trace_id=trace_id, summary=summary, log_diff=False)
            # Write down unfiltered summary into the _unfiltered file
            with open(str(summary_file_path).replace(".txt", "_unfiltered.txt"), "w") as f:
                f.write(unfiltered_summary)
            # Write new summary into the actual file
            with open(summary_file_path, "w") as f:
                f.write(cleaned_up_summary)
            # No need to generary a new summary again
            traces_processed_count += 1
            continue
        # Summarize trace
        logger.info("*" * 50)
        logger.info(f"Summary for trace {trace_id}:")
        start_time = time.time()
        summary = summarizer.generate_trace_summary(trace_messages_str)  # Call LLM
        end_time = time.time()
        response_time = round((end_time - start_time) * 1000)
        response_times_ms.append(response_time)
        token_counts.append(len(token_encoder.encode(summary)))
        logger.info(summary)
        # TODO: Check for the size of the generated summary, as in some very rare cases the summary could be extremely large (50+ tokens)
        # Write down unfiltered summary into the _unfiltered file
        unfiltered_summary = copy(summary)
        with open(str(summary_file_path).replace(".txt", "_unfiltered.txt"), "w") as f:
            f.write(unfiltered_summary)
        # Clean up the summary before embedding
        cleaned_up_summary = _clean_up_summary_before_embedding(trace_id=trace_id, summary=summary, log_diff=False)
        # Store generated summary in file
        with open(summary_file_path, "w") as f:
            f.write(cleaned_up_summary)
        traces_processed_count += 1
        logger.info(f"Processed {traces_processed_count}/{len(traces_dirs)} traces")
    # Calculate token stats
    token_stats = np.array(token_counts)
    logger.info("Stringified traces summaries token stats:")
    logger.info(f"Average token count: {token_stats.mean()}")
    logger.info(f"Median token count: {np.median(token_stats)}")
    logger.info(f"90th percentile token count: {np.percentile(token_stats, 90)}")
    logger.info(f"95th percentile token count: {np.percentile(token_stats, 95)}")
    logger.info(f"99th percentile token count: {np.percentile(token_stats, 99)}")
    logger.info(f"Min token count: {token_stats.min()}")
    logger.info(f"Max token count: {token_stats.max()}")
    # Calculate response time stats
    response_times_ms_stats = np.array(response_times_ms)
    logger.info("*" * 50)
    logger.info("*" * 50)
    logger.info("*" * 50)
    logger.info("Response time stats:")
    logger.info(f"Average response time: {response_times_ms_stats.mean()}")
    logger.info(f"Median response time: {np.median(response_times_ms_stats)}")
    logger.info(f"90th percentile response time: {np.percentile(response_times_ms_stats, 90)}")
    logger.info(f"95th percentile response time: {np.percentile(response_times_ms_stats, 95)}")
    logger.info(f"99th percentile response time: {np.percentile(response_times_ms_stats, 99)}")
    logger.info(f"Min response time: {response_times_ms_stats.min()}")
    logger.info(f"Max response time: {response_times_ms_stats.max()}")
