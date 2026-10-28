"""Workflow and activity envelopes for the intent topics pipeline."""

from dataclasses import dataclass, field
from typing import Any

RUN_KINDS = ("sync", "assign", "refit")


@dataclass(frozen=True)
class IntentTopicsWorkflowInputs:
    """One pipeline run for one team.

    ``kind`` selects the run: hourly ``sync``, nightly ``assign`` or weekly ``refit`` (which
    re-assigns the fit window when it succeeds). ``now`` is an ISO timestamp; when empty the
    activity uses the wall clock.
    """

    team_id: int
    kind: str = "sync"
    now: str = ""

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {"team_id": self.team_id, "kind": self.kind}


@dataclass(frozen=True)
class IntentTopicsRunResult:
    team_id: int
    kind: str
    status: str
    run_id: str = ""
    n_intents: int = 0
    n_topics: int = 0
    n_outliers: int = 0
    n_embeddings_requested: int = 0
    error_message: str = ""


@dataclass(frozen=False)
class IntentTopicsWorkflowResult:
    team_id: int
    kind: str
    runs: list[IntentTopicsRunResult] = field(default_factory=list)

    @property
    def status(self) -> str:
        return self.runs[-1].status if self.runs else "skipped"
