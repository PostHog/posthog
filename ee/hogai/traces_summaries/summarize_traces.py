# TODO: 1. Get traces through query runner
# TODO: 2. Stringify them in-memory
# TODO: 3. Generate summaries (store somewhere, Postgres for now, later would be stored in Olly's table)
# TODO: 4. Generate embeddings (should be included in the previous step)
# TODO: 5. Clusterize embeddings, return groups/singles/and group centroids


from posthog.schema import DateRange

from posthog.models.team.team import Team

from ee.hogai.traces_summaries.get_traces import TracesSummarizerCollector
from ee.hogai.traces_summaries.stringify_trace import TracesSummarizerStringifier


class TracesSummarizer:
    def __init__(self, team: Team):
        self._team = team

    def summarize_traces_for_date_range(self, date_range: DateRange) -> list[str]:
        collector = TracesSummarizerCollector(team=self._team)
        # Collect and stringify traces in-memory
        stringified_traces: dict[str, str] = {}  # trace_id -> stringified trace
        for traces_chunk in collector.collect_traces_to_analyze(date_range=date_range):
            stringified_traces_chunk = TracesSummarizerStringifier().stringify_traces(traces_chunk)
            stringified_traces.update(stringified_traces_chunk)
        # Summarize stringified traces
