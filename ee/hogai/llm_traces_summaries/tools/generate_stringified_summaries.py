import re
import asyncio
import difflib
from copy import copy

import structlog
from google import genai
from google.genai.types import GenerateContentConfig
from rich.console import Console

from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async

from products.llm_analytics.backend.providers.gemini import GeminiProvider

from ee.hogai.llm_traces_summaries.constants import LLM_TRACES_SUMMARIES_MODEL_TO_SUMMARIZE_STRINGIFIED_TRACES
from ee.models.llm_traces_summaries import LLMTraceSummary

logger = structlog.get_logger(__name__)

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


class LLMTraceSummarizerGenerator:
    def __init__(
        self,
        team: Team,
        model_id: str = LLM_TRACES_SUMMARIES_MODEL_TO_SUMMARIZE_STRINGIFIED_TRACES,
        summary_type: LLMTraceSummary.LLMTraceSummaryType = LLMTraceSummary.LLMTraceSummaryType.ISSUES_SEARCH,
    ):
        self._team = team
        self._summary_type = summary_type
        self._model_id = model_id
        self._provider = GeminiProvider(model_id=model_id)
        # # Using default Google client as posthog wrapper doesn't support `aio` yet for async calls
        self._client = genai.Client(api_key=self._provider.get_api_key())
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

    async def summarize_stringified_traces(self, stringified_traces: dict[str, str]) -> dict[str, str]:
        """Summarize a dictionary of stringified traces."""
        tasks = {}
        # Check which traces already have summaries to avoid re-generating them
        existing_trace_ids = await database_sync_to_async(self._check_existing_summaries)(
            trace_ids=list(stringified_traces.keys())
        )
        # Limit to 10 concurrent API calls
        semaphore = asyncio.Semaphore(10)
        async with asyncio.TaskGroup() as tg:
            limit = 100  # TODO: Temporary limit to test
            for trace_id, stringified_trace in list(stringified_traces.items())[:limit]:
                if trace_id in existing_trace_ids:
                    # Avoid re-generating summaries that already exist for this team + trace + type
                    continue
                tasks[trace_id] = tg.create_task(
                    self._generate_trace_summary_with_semaphore(
                        semaphore=semaphore, trace_id=trace_id, stringified_trace=stringified_trace
                    )
                )
        summarized_traces: dict[str, str] = {}
        for trace_id, task in tasks.items():
            res: str | Exception = task.result()
            if isinstance(res, Exception):
                logger.exception(
                    f"Failed to generate summary for trace {trace_id} from team {self._team.id} when summarizing traces: {res}",
                    error=str(res),
                )
                continue
            # If the summary generated is too large to store - skip it
            if len(res) > 1000:
                logger.warning(
                    f"Summary for trace {trace_id} from team {self._team.id} is too large to store (over 1000 characters), skipping",
                )
                continue
            # Return only successful summaries
            summarized_traces[trace_id] = res
        return summarized_traces

    async def _generate_trace_summary_with_semaphore(
        self, semaphore: asyncio.Semaphore, trace_id: str, stringified_trace: str
    ) -> str | Exception:
        """Wrapper to limit concurrent API calls using a semaphore."""
        async with semaphore:
            return await self._generate_trace_summary(trace_id=trace_id, stringified_trace=stringified_trace)

    async def _generate_trace_summary(self, trace_id: str, stringified_trace: str) -> str | Exception:
        prompt = GENERATE_STRINGIFIED_TRACE_SUMMARY_PROMPT.format(stringified_trace=stringified_trace)
        try:
            self._provider.validate_model(self._model_id)
            config_kwargs = self._provider.prepare_config_kwargs(system="")
            response = await self._client.aio.models.generate_content(
                model=self._model_id,
                contents=prompt,
                config=GenerateContentConfig(**config_kwargs),
            )
            # Avoid LLM returning excessive comments when no issues found
            if "no issues found" in response.text.lower() and response.text.lower() != "no issues found":
                logger.info(
                    f"Original 'no issues' text for trace {trace_id} from team {self._team.id} (replaced with 'No issues found'): {response.text}"
                )
                return "No issues found"
            if response.text.lower() == "no issues found":
                return "No issues found"
            cleaned_up_summary = self._clean_up_summary_before_embedding(trace_id=trace_id, summary=response.text)
            return cleaned_up_summary
        except Exception as err:
            return err  # Let caller handle the error

    def _clean_up_summary_before_embedding(self, trace_id: str, summary: str, log_diff: bool = False) -> str:
        """Remove repetitive phrases and excessive formatting to make embeddings more accurate."""
        original_summary = copy(summary)
        # Remove parts that don't add value
        for part in self._no_value_parts:
            summary = summary.replace(f" {part} ", " ")
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
            logger.warning(
                f"Summary for trace {trace_id} from team {self._team.id} is too different from the original summary "
                "(smaller 20%+ after cleanup) when summarizing traces",
            )
            # Force log diff if drastic difference
            log_diff = True
        if summary == original_summary or not log_diff:
            return summary
        # Log differences, if any, when asked explicitly
        self._log_diff(trace_id=trace_id, original_summary=original_summary, summary=summary)
        return summary

    def _log_diff(self, trace_id: str, original_summary: str, summary: str) -> None:
        """Optional helper function to log the differences between the original and cleaned up summaries."""
        logger.info(f"Summary cleaned up for trace {trace_id} from team {self._team.id} when summarizing traces")
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

    def store_summaries_in_db(self, summarized_traces: dict[str, str]):
        # Store summaries in the database should be part of the embedding process
        # Temporary PSQL solution to test end-to-end summarization pipeline
        # TODO: Should be replaced (or migrated to) later with the Clickhouse-powered solution to allow FTS
        summaries_batch_size = 500
        summaries_for_db = [
            LLMTraceSummary(team=self._team, trace_id=trace_id, summary=summary, trace_summary_type=self._summary_type)
            for trace_id, summary in summarized_traces.items()
        ]
        # Ignore already processed traces summaries, if they get to this stage
        LLMTraceSummary.objects.bulk_create(summaries_for_db, batch_size=summaries_batch_size, ignore_conflicts=True)

    def _check_existing_summaries(self, trace_ids: list[str]) -> set[str]:
        existing_trace_ids = set(
            LLMTraceSummary.objects.filter(
                team=self._team, trace_summary_type=self._summary_type, trace_id__in=trace_ids
            ).values_list("trace_id", flat=True)
        )
        return existing_trace_ids
