import re
import json
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

from ci_backend_master_artifacts import extract_artifact, validate_artifact_name
from ci_backend_master_receipts import DepotBinding, OwnerReceipt, depot_identifier
from ci_backend_master_store import Commands, integer, record, records, text

WORKFLOW = "ci-backend.yml"
ACTIVE_STATES = {"queued", "waiting", "running"}
TERMINAL_STATES = {"finished", "failed", "cancelled"}


def identifier(value: object) -> str:
    return depot_identifier(text(value))


@dataclass(frozen=True, kw_only=True, slots=True)
class DispatchReceipt:
    owner_digest: str
    organization_id: str
    run_id: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"[0-9a-f]{64}", self.owner_digest) is None:
            raise ValueError("Dispatch receipt must name its owner digest")
        identifier(self.organization_id)
        identifier(self.run_id)

    def to_json(self) -> str:
        return json.dumps({"version": 1, **asdict(self)}, sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> "DispatchReceipt":
        if len(payload) > 4096:
            raise ValueError("Dispatch receipt exceeds the size limit")
        parsed = record(json.loads(payload))
        if set(parsed) != {"version", "owner_digest", "organization_id", "run_id"} or integer(parsed["version"]) != 1:
            raise ValueError("Dispatch receipt has unsupported fields or version")
        return cls(
            owner_digest=text(parsed["owner_digest"]),
            organization_id=text(parsed["organization_id"]),
            run_id=text(parsed["run_id"]),
        )

    def validate(self, *, owner: OwnerReceipt, organization_id: str) -> None:
        if owner.engine != "depot" or self.owner_digest != owner.digest or self.organization_id != organization_id:
            raise ValueError("Dispatch receipt belongs to a different owner or organization")


class DepotMaster:
    def __init__(self, *, owner: OwnerReceipt, organization_id: str, commands: Commands) -> None:
        if owner.engine != "depot":
            raise ValueError("GitHub owns this master event")
        self.owner = owner
        self.organization_id = identifier(organization_id)
        self.commands = commands

    def json(self, *arguments: str) -> dict[str, object]:
        return record(
            self.commands.json(["depot", "ci", *arguments, "--org", self.organization_id, "--output", "json"])
        )

    def dispatch(self, *, existing: DispatchReceipt | None, run_attempt: int) -> DispatchReceipt:
        if existing is not None:
            existing.validate(owner=self.owner, organization_id=self.organization_id)
            return existing
        DepotBinding.resume(owner=self.owner, existing=None, run_attempt=run_attempt)
        master = self.owner.master
        # Depot documents branch/tag refs, not commit refs. The worker must authorize and check out master_sha.
        response = self.json(
            "dispatch",
            "--repo",
            master.repository,
            "--workflow",
            WORKFLOW,
            "--ref",
            "master",
            "--input",
            f"master_run_id={master.github_run_id}",
            "--input",
            f"master_sha={master.sha}",
            "--input",
            f"master_event={master.event}",
            "--input",
            f"master_schedule={master.schedule}",
        )
        if response.get("org_id") != self.organization_id:
            raise ValueError("Dispatch response names a different Depot organization")
        return DispatchReceipt(
            owner_digest=self.owner.digest,
            organization_id=self.organization_id,
            run_id=identifier(response.get("run_id")),
        )

    def bind(self, *, dispatch: DispatchReceipt) -> DepotBinding | None:
        dispatch.validate(owner=self.owner, organization_id=self.organization_id)
        status = self.json("status", dispatch.run_id)
        if status.get("org_id") != self.organization_id or status.get("run_id") != dispatch.run_id:
            raise ValueError("Depot status does not match the dispatch receipt")
        workflows = records(status.get("workflows"))
        matching = [workflow for workflow in workflows if workflow.get("workflow_path") == WORKFLOW]
        if not matching:
            if status.get("status") in ACTIVE_STATES:
                return None
            raise ValueError("Depot dispatch ended without the backend workflow")
        if len(matching) != 1 or len(workflows) != 1:
            raise ValueError("Depot dispatch does not identify exactly one backend workflow")
        return DepotBinding(
            owner_digest=self.owner.digest,
            organization_id=self.organization_id,
            workflow_id=identifier(matching[0].get("workflow_id")),
        )

    def workflow(self, *, dispatch: DispatchReceipt, binding: DepotBinding) -> dict[str, object]:
        dispatch.validate(owner=self.owner, organization_id=self.organization_id)
        binding.authorize(
            owner=self.owner,
            master=self.owner.master,
            organization_id=self.organization_id,
            workflow_id=binding.workflow_id,
        )
        response = self.json("workflow", "show", binding.workflow_id)
        run = record(response.get("run"))
        workflow = record(response.get("workflow"))
        if (
            response.get("org_id") != self.organization_id
            or run.get("run_id") != dispatch.run_id
            or run.get("repo") != self.owner.master.repository
            or run.get("trigger") != "workflow_dispatch"
            or workflow.get("workflow_id") != binding.workflow_id
            or workflow.get("workflow_path") != WORKFLOW
        ):
            raise ValueError("Depot workflow does not match the canonical dispatch")
        return response

    @staticmethod
    def verdict(workflow: dict[str, object]) -> str:
        state = text(record(workflow.get("workflow")).get("status"))
        if state in ACTIVE_STATES:
            return "pending"
        if state not in TERMINAL_STATES:
            raise ValueError("Depot workflow returned an unknown state")
        gates = [job for job in records(workflow.get("jobs")) if job.get("job_key") == f"{WORKFLOW}:django_tests"]
        if state == "finished" and len(gates) == 1 and gates[0].get("status") == "finished":
            return "success"
        return "failure"

    def collect_artifacts(
        self, *, dispatch: DispatchReceipt, binding: DepotBinding, workflow: dict[str, object], destination: Path
    ) -> list[dict[str, str]]:
        dispatch.validate(owner=self.owner, organization_id=self.organization_id)
        binding.authorize(
            owner=self.owner,
            master=self.owner.master,
            organization_id=self.organization_id,
            workflow_id=binding.workflow_id,
        )
        if self.verdict(workflow) == "pending":
            raise ValueError("Wait for the Depot workflow before collecting artifacts")
        jobs = records(workflow.get("jobs"))
        latest_attempts: dict[str, str] = {}
        for job in jobs:
            attempts = records(job.get("attempts"))
            if attempts:
                latest = max(attempts, key=lambda attempt: integer(attempt.get("attempt")))
                latest_attempts[identifier(job.get("job_id"))] = identifier(latest.get("attempt_id"))
        listing = self.json("artifacts", "list", dispatch.run_id, "--workflow", binding.workflow_id)
        artifacts = records(listing.get("artifacts"))
        selected: dict[str, dict[str, object]] = {}
        for artifact in artifacts:
            if artifact.get("run_id") != dispatch.run_id or artifact.get("workflow_id") != binding.workflow_id:
                raise ValueError("Artifact does not belong to the bound Depot workflow")
            job_id = identifier(artifact.get("job_id"))
            if job_id not in latest_attempts:
                raise ValueError("Artifact does not belong to a known job attempt")
            if artifact.get("attempt_id") != latest_attempts[job_id]:
                continue
            name = validate_artifact_name(text(artifact.get("name")))
            if name in selected:
                raise ValueError("Bound Depot workflow has duplicate artifact names")
            selected[name] = artifact
        if (
            len(selected) > 256
            or sum(integer(artifact.get("size_bytes")) for artifact in selected.values()) > 8 * 1024**3
        ):
            raise ValueError("Depot artifacts exceed the relay budget")
        destination.mkdir(parents=True, exist_ok=False)
        manifest: list[dict[str, str]] = []
        remaining_bytes = 8 * 1024**3
        for index, (name, artifact) in enumerate(sorted(selected.items())):
            archive = destination / f"download-{index}.zip"
            self.commands.run(
                [
                    "depot",
                    "ci",
                    "artifacts",
                    "download",
                    identifier(artifact.get("artifact_id")),
                    "--org",
                    self.organization_id,
                    "--output-file",
                    str(archive),
                ],
                timeout=300,
            )
            try:
                with zipfile.ZipFile(archive) as contents:
                    size = sum(member.file_size for member in contents.infolist())
                if size > remaining_bytes or remaining_bytes == 0:
                    raise ValueError("Decompressed artifacts exceed the relay budget")
                extract_artifact(archive, destination / name, max_bytes=min(2 * 1024**3, remaining_bytes))
                remaining_bytes -= size
            finally:
                archive.unlink(missing_ok=True)
            manifest.append({"name": name, "path": str(destination / name)})
        return manifest
