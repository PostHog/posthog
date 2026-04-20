from typing import Never

# we keep the history here for numeric ordering,
# but we don't need these session_recording_event migrations on new hobby or dev instances
operations: list[Never] = []
