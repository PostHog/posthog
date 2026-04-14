import re


class EventsPrefilterTransformer:
    """Wraps non-first FROM events in ClickHouse SQL with a prefiltered subquery.

    Used by WebStatsTableQueryRunner for bounce and avg-time queries that scan
    the events table multiple times. All FROM events occurrences get wrapped:

        FROM events → FROM (SELECT * FROM events WHERE <prefilter>) AS events

    This forces ClickHouse to prune granules on the primary key
    (team_id, toDate(timestamp), event) BEFORE evaluating the expensive
    session and person override JOINs that the lazy resolver attaches.

    This transformer only modifies the SQL string — it does not touch the AST.
    It is intentionally scoped to WebStatsTableQueryRunner and is not a generic
    HogQL feature.
    """

    def __init__(self, team_id: int, date_from: str, date_to: str):
        self.team_id = team_id
        self.date_from = date_from
        self.date_to = date_to

    @property
    def prefilter_clause(self) -> str:
        return (
            f"events.team_id = {self.team_id}"
            f" AND toDate(events.timestamp) >= '{self.date_from}'"
            f" AND toDate(events.timestamp) <= '{self.date_to}'"
        )

    def transform(self, sql: str) -> str:
        # Match FROM events followed by whitespace or end-of-line/closing paren context.
        # Use a word boundary after 'events' to avoid matching 'events_backup' etc.
        pattern = re.compile(r"(\bFROM\s+)(events)\b", re.IGNORECASE)
        matches = list(pattern.finditer(sql))

        if len(matches) == 0:
            return sql

        # Replace from last to first to preserve string indices.
        for match in reversed(matches):
            replacement = f"{match.group(1)}(SELECT * FROM events WHERE {self.prefilter_clause}) AS events"
            sql = sql[: match.start()] + replacement + sql[match.end() :]

        return sql
