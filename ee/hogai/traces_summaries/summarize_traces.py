# TODO: 1. Get traces through query runner
# TODO: 2. Stringify them in-memory
# TODO: 3. Generate summaries (store somewhere, Postgres for now, later would be stored in Olly's table)
# TODO: 4. Generate embeddings (should be included in the previous step)
# TODO: 5. Clusterize embeddings, return groups/singles/and group centroids


from posthog.schema import DateRange

from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async

from ee.hogai.traces_summaries.embed_summaries import TracesSummarizerEmbedder
from ee.hogai.traces_summaries.generate_stringified_summaries import TraceSummarizerGenerator
from ee.hogai.traces_summaries.get_traces import TracesSummarizerCollector
from ee.hogai.traces_summaries.stringify_trace import TracesSummarizerStringifier

# def collect_traces_to_analyze(self, date_range: DateRange) -> Generator[list[LLMTrace], None, None]:
#     """
#     Collect traces, return page by page to avoid storing too many full traces in memory at once.
#     """
#     offset = 0


class TracesSummarizer:
    def __init__(self, team: Team):
        self._team = team

    async def summarize_traces_for_date_range(self, date_range: DateRange) -> None:
        collector = TracesSummarizerCollector(team=self._team)
        # Collect and stringify traces in-memory
        stringifier = TracesSummarizerStringifier(team=self._team)
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
        summary_generator = TraceSummarizerGenerator(team=self._team)
        summarized_traces = await summary_generator.summarize_stringified_traces(stringified_traces=stringified_traces)
        # Store summaries in the database
        await database_sync_to_async(summary_generator.store_summaries_in_db)(summarized_traces=summarized_traces)
        # Embed summaries
        embedder = TracesSummarizerEmbedder(team=self._team)
        embedder.embed_summaries(summarized_traces=summarized_traces)
        # Returns nothing if everything succeeded
        return None
