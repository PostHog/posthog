# TODO: 1. Get traces through query runner
# TODO: 2. Stringify them in-memory
# TODO: 3. Generate summaries (store somewhere, Postgres for now, later would be stored in Olly's table)
# TODO: 4. Generate embeddings (should be included in the previous step)
# TODO: 5. Clusterize embeddings, return groups/singles/and group centroids


from ee.hogai.traces_summaries.generate_stringified_summaries import TraceSummarizerGenerator
from posthog.schema import DateRange

from posthog.models.team.team import Team

from ee.hogai.traces_summaries.get_traces import TracesSummarizerCollector
from ee.hogai.traces_summaries.stringify_trace import TracesSummarizerStringifier


class TracesSummarizer:
    def __init__(self, team: Team):
        self._team = team

    async def summarize_traces_for_date_range(self, date_range: DateRange) -> list[str]:
        collector = TracesSummarizerCollector(team=self._team)
        # Collect and stringify traces in-memory
        stringifier = TracesSummarizerStringifier(team=self._team)
        stringified_traces: dict[str, str] = {}  # trace_id -> stringified trace
        for traces_chunk in collector.collect_traces_to_analyze(date_range=date_range):
            stringified_traces_chunk = stringifier.stringify_traces(traces_chunk)
            stringified_traces.update(stringified_traces_chunk)
        # Summarize stringified traces
        summary_generator = TraceSummarizerGenerator(team=self._team)
        summarized_traces = await summary_generator.summarize_stringified_traces(stringified_traces=stringified_traces)
