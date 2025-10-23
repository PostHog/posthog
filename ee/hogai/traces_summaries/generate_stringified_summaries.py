import re
import difflib
from copy import copy

import structlog
from rich.console import Console

from products.llm_analytics.backend.providers.gemini import GeminiProvider

logger = structlog.get_logger(__name__)

LLM_MODEL_TO_SUMMARIZE_STRINGIFIED_TRACES = "gemini-2.5-flash-lite-preview-09-2025"

GENERATE_STRINGIFIED_TRACE_SUMMARY_PROMPT = """
- Analyze this conversation between the user and the PostHog AI assistant
- List all pain points, frustrations, and feature limitations the user experienced.
- IMPORTANT: Count only specific issues the user experienced when interacting with the assistant, don't guess or suggest.
- If no issues - return only "No issues found" text, without any additional comments.
- If issues found - provide output as plain English text in a maximum of 10 sentences, while highlighting all the crucial parts.

```
{stringified_trace}
```
"""

console = Console()


class TraceSummarizerGenerator:
    def __init__(self, model_id: str = LLM_MODEL_TO_SUMMARIZE_STRINGIFIED_TRACES):
        self._model_id = model_id
        self._provider = GeminiProvider(model_id=model_id)
        # Remove excessive summary parts that add no value to concentrate the summary meaning programmatically
        # Parts that add no value and can't be safely removed
        self._no_value_parts = [
            "several",
            "during the interaction",
            "explicitly",
        ]
        # Repeating prefixes (model-specific)
        self._excessive_prefixes = ["The user experienced"]
        # Excessive markdown formatting (model-specific)
        self._excessive_formatting = ["**"]
        # Narrative words (one word before comma at the start of the sentence), like "Next, " or "Finally, "
        self._narrative_words_regex = r"(^|\n|\.\"\s|\.\s)([A-Z]\w+, )"
        # Ensure the summary is readable after the clean-up
        self._proper_capitalization_regex = (
            r"(\.\s|\n\s|\.\"\s|^)([a-z])"  # Replace lowercase letters with uppercase at the start of the sentence
        )
        # TODO: Copy stats collection from "old_summarize_trace.py"

    def summarize_stringified_traces(self, stringified_traces: dict[str, str]) -> dict[str, str]:
        """Summarize a dictionary of stringified traces."""
        summarized_traces: dict[str, str] = {}
        for trace_id, stringified_trace in stringified_traces.items():
            summarized_trace = self._generate_trace_summary(trace_id=trace_id, stringified_trace=stringified_trace)
            summarized_traces[trace_id] = summarized_trace
        return summarized_traces

    def _generate_trace_summary(self, trace_id: str, stringified_trace: str) -> str:
        prompt = GENERATE_STRINGIFIED_TRACE_SUMMARY_PROMPT.format(stringified_trace=stringified_trace)
        response_text = self._provider.get_response(prompt=prompt, system="")
        # Avoid LLM returning excessive comments when no issues found
        if "no issues found" in response_text.lower() and response_text.lower() != "no issues found":
            logger.info(
                f"Original 'no issues' text for trace {trace_id} (replaced with 'No issues found'): {response_text}"
            )
            return "No issues found"
        cleaned_up_summary = self._clean_up_summary_before_embedding(trace_id=trace_id, summary=response_text)
        return cleaned_up_summary

    def _clean_up_summary_before_embedding(self, trace_id: str, summary: str, log_diff: bool = False) -> str:
        """Remove repetitive phrases and excessive formatting to make embeddings more accurate."""
        original_summary = copy(summary)
        # Remove parts that don't add value
        for part in self._no_value_parts:
            summary = summary.replace(part, " ")
        # Remove excessive prefixes
        for prefix in self._excessive_prefixes:
            while True:
                # Remove all occurrences
                prefix_index = summary.find(prefix)
                if prefix_index == -1:
                    # Not found
                    break
                # Remove prefix
                summary = summary[:prefix_index] + summary[prefix_index + len(prefix) :]
        # Remove narrative words (one word before comma at the start of the sentence)
        summary = re.sub(self._narrative_words_regex, lambda m: m.group(1), summary)
        # Remove excessive formatting
        for formatting in self._excessive_formatting:
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
        summary = re.sub(self._proper_capitalization_regex, lambda m: m.group(1) + m.group(2).upper(), summary)
        if len(summary) / len(original_summary) <= 0.8:
            # Force log diff if drastic difference
            log_diff = True
        if summary == original_summary or not log_diff:
            return summary
        # Log differences, if any, whhen asked explicitly
        self._log_diff(trace_id=trace_id, original_summary=original_summary, summary=summary)
        return summary

    @staticmethod
    def _log_diff(trace_id: str, original_summary: str, summary: str) -> None:
        """Helper function to log the differences between the original and cleaned up summaries."""
        logger.warning(
            f"Summary cleaned up for trace {trace_id} when summarizing traces",
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
