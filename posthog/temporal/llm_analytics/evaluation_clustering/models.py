"""Data models for evaluation clustering workflows."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SamplerActivityInputs:
    """Inputs for the per-job sample_and_embed activity.

    Stage A runs one of these per (team, active evaluation ClusteringJob) per hour.
    The window is computed by the workflow (not the activity) so that replays
    are deterministic.
    """

    team_id: int
    job_id: str
    job_name: str
    run_ts: str  # ISO timestamp tag used in the embedding `rendering` value
    window_start: str  # ISO
    window_end: str  # ISO
    max_samples: int
    event_filters: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SamplerActivityResult:
    """Outcome of one per-job sampler activity run."""

    team_id: int
    job_id: str
    sampled: int
    embedded: int  # we enqueue one Kafka message per sampled row, this is the count produced


@dataclass
class SamplerWorkflowInputs:
    """Inputs for the per-job sampler child workflow."""

    team_id: int
    job_id: str
    job_name: str
    event_filters: list[dict[str, Any]] = field(default_factory=list)
    max_samples: int | None = None  # None → falls back to SAMPLER_MAX_SAMPLES_PER_JOB
    # Optional explicit window; when absent the workflow derives it from workflow.now().
    # Mostly useful for tests and for manual replays.
    window_start: str | None = None
    window_end: str | None = None

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {"team_id": self.team_id, "job_id": self.job_id, "job_name": self.job_name}


@dataclass
class SamplerWorkflowResult:
    """Result from a single per-job sampler workflow run."""

    team_id: int
    job_id: str
    sampled: int
    embedded: int
    window_start: str
    window_end: str


@dataclass
class SamplerCoordinatorResult:
    """Aggregate result from a sampler coordinator run."""

    jobs_dispatched: int
    jobs_succeeded: int
    jobs_failed: int
    total_sampled: int
    total_embedded: int
