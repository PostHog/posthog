from posthog.temporal.session_replay.copy_recording.activities import copy_session_recording
from posthog.temporal.session_replay.copy_recording.workflow import CopyRecordingsWorkflow

COPY_RECORDING_WORKFLOWS = [CopyRecordingsWorkflow]

COPY_RECORDING_ACTIVITIES = [copy_session_recording]
