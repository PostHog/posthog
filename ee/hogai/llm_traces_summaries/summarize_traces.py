# TODO: 1. Get traces through query runner
# TODO: 2. Stringify them in-memory
# TODO: 3. Generate summaries (store somewhere, Postgres for now, later would be stored in Olly's table)
# TODO: 4. Generate embeddings (should be included in the previous step)
# TODO: 5. Clusterize embeddings, return groups/singles/and group centroids


from ee.models.llm_traces_summaries import LLMTraceSummary
from posthog.schema import DateRange

from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async

from ee.hogai.llm_traces_summaries.embed_summaries import LLMTracesSummarizerEmbedder
from ee.hogai.llm_traces_summaries.generate_stringified_summaries import LLMTraceSummarizerGenerator
from ee.hogai.llm_traces_summaries.get_traces import LLMTracesSummarizerCollector
from ee.hogai.llm_traces_summaries.stringify_trace import LLMTracesSummarizerStringifier


class LLMTracesSummarizer:
    def __init__(self, team: Team):
        self._team = team

    async def summarize_traces_for_date_range(self, date_range: DateRange) -> None:
        """Get, stringify, summarize, embed and store summaries for all traces in the date range."""
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
        # Summarize stringified traces
        summary_generator = LLMTraceSummarizerGenerator(team=self._team)
        summarized_traces = await summary_generator.summarize_stringified_traces(stringified_traces=stringified_traces)
        # Store summaries in the database
        await database_sync_to_async(summary_generator.store_summaries_in_db)(summarized_traces=summarized_traces)
        # Embed summaries
        embedder = LLMTracesSummarizerEmbedder(team=self._team)
        embedder.embed_summaries(summarized_traces=summarized_traces, summary_type=LLMTraceSummary.LLMTraceSummaryType.ISSUES_SEARCH)
        # Returns nothing if everything succeeded
        return None

    def find_top_similar_traces_for_query(self, query: str, top: int, date_range: DateRange) -> list[dict[str, str]]:
        """Search all summarized traces for the query and return the top similar traces."""

