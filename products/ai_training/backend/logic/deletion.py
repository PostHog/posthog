import uuid
from collections.abc import Sequence

from posthog.hogql import ast

from posthog.models.team.team import Team

from products.ai_training.backend.config import privacy_enabled
from products.ai_training.backend.models import AITrainingDeletionRequest


def queue_training_deletion(team_id: int, kind: str, identifiers: Sequence[str] = ()) -> None:
    if not privacy_enabled():
        return
    if kind not in {"team", "session"}:
        raise ValueError("Unsupported AI training deletion scope")
    if kind == "session":
        normalized = []
        for value in identifiers:
            try:
                session_id = uuid.UUID(value)
            except (ValueError, AttributeError):
                continue
            if session_id.version == 7:
                normalized.append(str(session_id))
        identifiers = normalized
    unique = sorted(set(identifiers))
    if kind != "team" and not unique:
        return
    requests = [
        AITrainingDeletionRequest(team_id=team_id, kind=kind, identifiers=unique[offset : offset + 1000])
        for offset in range(0, max(1, len(unique)), 1000)
    ]
    AITrainingDeletionRequest.objects.for_team(team_id).bulk_create(requests)


def queue_person_training_deletion(team_id: int, distinct_ids: Sequence[str]) -> None:
    if not privacy_enabled() or not distinct_ids:
        return
    from posthog.hogql.query import execute_hogql_query  # noqa: PLC0415 - Keep HogQL off startup.

    team = Team.objects.get(id=team_id)
    unique = sorted(set(distinct_ids))
    for offset in range(0, len(unique), 1000):
        cursor = ""
        while True:
            response = execute_hogql_query(
                query="""
                    SELECT session_id
                    FROM raw_session_replay_events
                    WHERE distinct_id IN {distinct_ids} AND session_id > {cursor}
                    GROUP BY session_id
                    ORDER BY session_id
                    LIMIT 1000
                """,
                team=team,
                query_type="AITrainingPersonDeletion",
                placeholders={
                    "distinct_ids": ast.Tuple(
                        exprs=[ast.Constant(value=value) for value in unique[offset : offset + 1000]]
                    ),
                    "cursor": ast.Constant(value=cursor),
                },
            )
            sessions = [str(row[0]) for row in response.results or []]
            queue_training_deletion(team_id, "session", sessions)
            if len(sessions) < 1000:
                break
            cursor = sessions[-1]
