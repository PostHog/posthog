from dataclasses import dataclass


@dataclass(frozen=True)
class SummarizeMCPSessionIntentsInput:
    # How many sessions to summarize per workflow run. The activity dispatches
    # OpenAI calls in parallel up to `concurrency`, so this cap mostly controls
    # OpenAI spend per tick.
    batch_size: int = 100

    # Maximum concurrent OpenAI requests in flight inside the activity. Higher
    # values trade memory + risk of OpenAI rate limits for shorter wall-clock.
    concurrency: int = 8

    # Skip sessions whose last event is too recent — they may still be active and
    # would have to be re-summarised. Only candidate sessions whose session_end is
    # older than this many minutes are eligible.
    idle_minutes: int = 30
