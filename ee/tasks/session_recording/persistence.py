from ee.models.session_recording_extensions import persist_recording


def persist_single_recording(id: str, team_id: int) -> None:
    persist_recording(id, team_id)
