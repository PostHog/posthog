from typing import List, Any

from posthog.models import Team


# stub - will be introduced in https://github.com/PostHog/posthog/pull/20046
def generate_recording_embedding(session_id: str, team_id: int) -> None:
    pass


# stub - will be introduced in https://github.com/PostHog/posthog/pull/20046
def fetch_recordings_without_embeddings(team: Team) -> List[Any]:
    return []
