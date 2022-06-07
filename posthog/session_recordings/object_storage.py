def object_storage_snapshot_path(team_id: int, session_recording_id: str) -> str:
    return f"session-recordings/session-recordings/team_id={team_id}/session_id={session_recording_id}/"
