class RecordingTemporal:
    """Stands in for the Temporal client and records each schedule it was asked to pause, with its note."""

    def __init__(self, failing: frozenset[str] = frozenset()) -> None:
        self.paused: list[tuple[str, str | None]] = []
        self.failing = failing

    def get_schedule_handle(self, schedule_id: str) -> "RecordingScheduleHandle":
        return RecordingScheduleHandle(self, schedule_id)


class RecordingScheduleHandle:
    def __init__(self, temporal: RecordingTemporal, schedule_id: str) -> None:
        self.temporal = temporal
        self.schedule_id = schedule_id

    async def pause(self, note: str | None = None) -> None:
        if self.schedule_id in self.temporal.failing:
            raise RuntimeError("Temporal is unavailable")
        self.temporal.paused.append((self.schedule_id, note))
