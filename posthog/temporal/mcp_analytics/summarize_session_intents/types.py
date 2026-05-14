from dataclasses import dataclass


@dataclass(frozen=True)
class SummarizeMCPSessionIntentsInput:
    # How many sessions to summarize per workflow run. Keeps the activity bounded
    # so we don't burn through OpenAI quota in a single tick.
    batch_size: int = 25
