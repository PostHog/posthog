import re
import json
import hashlib
from dataclasses import asdict, dataclass
from typing import Literal, cast

Engine = Literal["github", "depot"]
MasterLane = Literal["push", "schedule"]
DEPOT_IDENTIFIER_PATTERN = r"[a-z0-9][a-z0-9_-]{0,99}"


def depot_identifier(value: str) -> str:
    if re.fullmatch(DEPOT_IDENTIFIER_PATTERN, value) is None:
        raise ValueError("Receipt must name a valid Depot identifier")
    return value


def _positive_integer(value: object, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _record(payload: str, fields: set[str]) -> dict[str, object]:
    if len(payload) > 4096:
        raise ValueError("Receipt exceeds the size limit")
    parsed: object = json.loads(payload)
    if not isinstance(parsed, dict) or set(parsed) != fields | {"version"}:
        raise ValueError("Receipt has unexpected fields")
    if type(parsed["version"]) is not int or parsed["version"] != 1:
        raise ValueError("Receipt version is not supported")
    return cast(dict[str, object], parsed)


# These scripts run without the application dependencies installed.
@dataclass(frozen=True, kw_only=True, slots=True)
class MasterEvent:
    repository: str
    github_run_id: int
    sha: str
    event: MasterLane
    ref: str = "refs/heads/master"
    schedule: str = ""

    def __post_init__(self) -> None:
        if re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+", self.repository
        ) is None or self.repository.rsplit("/", 1)[-1] in (".", ".."):
            raise ValueError("Repository must have an owner and name")
        _positive_integer(self.github_run_id, "github_run_id")
        if re.fullmatch(r"[0-9a-f]{40}", self.sha) is None:
            raise ValueError("Master event must pin a full commit SHA")
        if self.ref != "refs/heads/master" or self.event not in ("push", "schedule"):
            raise ValueError("Only master pushes and schedules can use this receipt")
        if self.event == "push" and self.schedule:
            raise ValueError("Push receipts cannot name a schedule")
        if self.event == "schedule" and (not self.schedule.strip() or not self.schedule.isprintable()):
            raise ValueError("Schedule receipts must name their cron expression")


@dataclass(frozen=True, kw_only=True, slots=True)
class OwnerReceipt:
    """Wire format for a decision persisted by the canonical GitHub run."""

    master: MasterEvent
    engine: Engine

    def __post_init__(self) -> None:
        if self.engine not in ("github", "depot"):
            raise ValueError("Receipt must name one engine")

    def to_json(self) -> str:
        return json.dumps({"version": 1, **asdict(self.master), "engine": self.engine}, sort_keys=True)

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_json().encode()).hexdigest()

    @classmethod
    def from_json(cls, payload: str) -> "OwnerReceipt":
        record = _record(payload, {"repository", "github_run_id", "sha", "event", "ref", "schedule", "engine"})
        return cls(
            master=MasterEvent(
                repository=_string(record["repository"], "repository"),
                github_run_id=_positive_integer(record["github_run_id"], "github_run_id"),
                sha=_string(record["sha"], "sha"),
                event=cast(MasterLane, _string(record["event"], "event")),
                ref=_string(record["ref"], "ref"),
                schedule=_string(record["schedule"], "schedule"),
            ),
            engine=cast(Engine, _string(record["engine"], "engine")),
        )

    @classmethod
    def choose(
        cls, *, master: MasterEvent, mode: str, run_attempt: int, existing: "OwnerReceipt | None"
    ) -> "OwnerReceipt":
        _positive_integer(run_attempt, "run_attempt")
        if existing is not None:
            if existing.master != master:
                raise ValueError("Existing owner receipt belongs to another event")
            return existing
        if run_attempt != 1:
            raise ValueError("Rerun has no owner receipt; do not choose a new engine")
        if mode not in ("", "github", "schedule", "all"):
            raise ValueError("Master lane mode must be github, schedule, or all")
        engine: Engine = "depot" if mode == "all" or (mode == "schedule" and master.event == "schedule") else "github"
        return cls(master=master, engine=engine)


@dataclass(frozen=True, kw_only=True, slots=True)
class DepotBinding:
    owner_digest: str
    organization_id: str
    workflow_id: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"[0-9a-f]{64}", self.owner_digest) is None:
            raise ValueError("Binding must name the owner receipt digest")
        for value in (self.organization_id, self.workflow_id):
            depot_identifier(value)

    def to_json(self) -> str:
        return json.dumps({"version": 1, **asdict(self)}, sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> "DepotBinding":
        record = _record(payload, {"owner_digest", "organization_id", "workflow_id"})
        return cls(
            owner_digest=_string(record["owner_digest"], "owner_digest"),
            organization_id=_string(record["organization_id"], "organization_id"),
            workflow_id=_string(record["workflow_id"], "workflow_id"),
        )

    def authorize(self, *, owner: OwnerReceipt, master: MasterEvent, organization_id: str, workflow_id: str) -> None:
        """The caller must read both receipts from the canonical GitHub run."""
        if owner.engine != "depot" or owner.master != master or self.owner_digest != owner.digest:
            raise ValueError("Depot workflow does not own this master event")
        if self.organization_id != organization_id or self.workflow_id != workflow_id:
            raise ValueError("This Depot workflow is not the bound owner")

    @classmethod
    def resume(cls, *, owner: OwnerReceipt, existing: "DepotBinding | None", run_attempt: int) -> "DepotBinding | None":
        """Call once per GitHub job; do not retry a dispatch in place."""
        _positive_integer(run_attempt, "run_attempt")
        if owner.engine != "depot":
            raise ValueError("GitHub owns this event; do not dispatch Depot")
        if existing is not None:
            if existing.owner_digest != owner.digest:
                raise ValueError("Existing Depot binding belongs to another owner receipt")
            return existing
        # A dispatch may succeed before its binding is uploaded. Retrying can duplicate side effects.
        if run_attempt != 1:
            raise ValueError("Dispatch outcome is unknown; recover the original Depot run instead of dispatching again")
        return None
