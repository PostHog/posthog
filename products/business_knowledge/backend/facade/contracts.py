from posthog.dataclasses import frozen


@frozen
class KnowledgeUsageByTeam:
    """Business knowledge usage in a period, as (team_id, total) rows per meter, for the usage report."""

    chunks: list[tuple[int, int]]
    queries: list[tuple[int, int]]


@frozen
class KnowledgeHit:
    document_title: str
    heading_path: str
    url: str
    content: str
