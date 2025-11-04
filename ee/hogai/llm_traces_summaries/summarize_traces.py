import structlog

from posthog.schema import DateRange

from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async

from ee.hogai.llm_traces_summaries.tools.embed_summaries import LLMTracesSummarizerEmbedder
from ee.hogai.llm_traces_summaries.tools.find_similar_traces import LLMTracesSummarizerFinder
from ee.hogai.llm_traces_summaries.tools.generate_stringified_summaries import LLMTraceSummarizerGenerator
from ee.hogai.llm_traces_summaries.tools.get_traces import LLMTracesSummarizerCollector
from ee.hogai.llm_traces_summaries.tools.stringify_trace import LLMTracesSummarizerStringifier
from ee.hogai.llm_traces_summaries.utils.load_from_csv import load_traces_from_csv_files
from ee.models.llm_traces_summaries import LLMTraceSummary

logger = structlog.get_logger(__name__)


class LLMTracesSummarizer:
    def __init__(self, team: Team):
        self._team = team

    async def summarize_traces_for_date_range(self, date_range: DateRange) -> None:
        """Get, stringify, summarize, embed and store summaries for all traces in the date range."""
        stringified_traces = await self._collect_and_stringify_traces_for_date_range(date_range=date_range)
        # Summarize stringified traces
        await self._summarize_stringified_traces(stringified_traces=stringified_traces)
        # Returns nothing if everything succeeded
        return None

    async def _collect_and_stringify_traces_for_date_range(self, date_range: DateRange) -> dict[str, str]:
        collector = LLMTracesSummarizerCollector(team=self._team)
        # Collect and stringify traces in-memory
        stringifier = LLMTracesSummarizerStringifier(team=self._team)
        stringified_traces: dict[str, str] = {}  # trace_id -> stringified trace
        offset = 0

        # Iterate to collect and stringify all traces in the date range
        while True:
            # Processing in chunks to avoid storing all heavy traces in memory at once (stringified ones are way lighter)
            response = await database_sync_to_async(collector.get_db_traces_per_page)(
                offset=offset, date_range=date_range
            )
            results = response.results
            offset += len(results)
            if len(results) == 0:
                break
            stringified_traces_chunk = stringifier.stringify_traces(traces_chunk=results)
            stringified_traces.update(stringified_traces_chunk)
            if response.hasMore is not True:
                break
        return stringified_traces

    async def summarize_traces_from_csv_files(self, csv_paths: list[str]) -> None:
        """Collect and stringify traces from CSV files and summarize them, useful for local development"""
        stringified_traces = self._collect_and_stringify_traces_from_csv_files(csv_paths=csv_paths)
        # Summarize stringified traces
        await self._summarize_stringified_traces(stringified_traces=stringified_traces)
        return None

    def _collect_and_stringify_traces_from_csv_files(self, csv_paths: list[str]) -> dict[str, str]:
        # Collect and stringify traces in-memory
        stringifier = LLMTracesSummarizerStringifier(team=self._team)
        stringified_traces: dict[str, str] = {}  # trace_id -> stringified trace
        for trace in load_traces_from_csv_files(csv_paths=csv_paths):
            stringified_trace = stringifier.stringify_traces(traces_chunk=[trace])
            stringified_traces.update(stringified_trace)
        return stringified_traces

    async def _summarize_stringified_traces(self, stringified_traces: dict[str, str]) -> dict[str, str]:
        # Summarize stringified traces
        summary_generator = LLMTraceSummarizerGenerator(team=self._team)
        summarized_traces = await summary_generator.summarize_stringified_traces(stringified_traces=stringified_traces)
        # Store summaries in the database
        await database_sync_to_async(summary_generator.store_summaries_in_db)(summarized_traces=summarized_traces)
        # Embed summaries
        embedder = LLMTracesSummarizerEmbedder(team=self._team)
        embedder.embed_summaries(
            summarized_traces=summarized_traces, summary_type=LLMTraceSummary.LLMTraceSummaryType.ISSUES_SEARCH
        )
        # Returns nothing if everything succeeded
        return None

    def find_top_similar_traces_for_query(
        self,
        query: str,
        request_id: str,
        top: int,
        date_range: DateRange,
        summary_type: LLMTraceSummary.LLMTraceSummaryType,
    ):
        """Search all summarized traces withi the date range for the query and return the top similar traces."""
        finder = LLMTracesSummarizerFinder(team=self._team)
        return finder.find_top_similar_traces_for_query(
            query=query,
            request_id=request_id,
            top=top,
            date_range=date_range,
            summary_type=summary_type,
        )
