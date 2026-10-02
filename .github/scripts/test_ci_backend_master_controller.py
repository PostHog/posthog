import io
import json
import zipfile
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from ci_backend_master_controller import MasterController, main
from ci_backend_master_depot import DispatchReceipt
from ci_backend_master_receipts import DepotBinding, Engine, MasterEvent, OwnerReceipt
from ci_backend_master_store import BINDING_ARTIFACT, DISPATCH_ARTIFACT, OWNER_ARTIFACT, Commands, GitHubReceipts

MASTER = MasterEvent(repository="example/repo", github_run_id=101, sha="a" * 40, event="push")
ORG = "example_org-1"
RUN = "dispatch_run"
WORKFLOW = "example_workflow-1"


def zipped(filename: str, payload: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(filename, payload)
    return buffer.getvalue()


class FakeCommands(Commands):
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.dispatch_failure = False
        self.receipts: list[dict[str, object]] = []
        self.downloads: dict[int, bytes] = {}
        self.run_payload: dict[str, object] = {
            "id": MASTER.github_run_id,
            "repository": {"full_name": MASTER.repository},
            "head_branch": "master",
            "head_sha": MASTER.sha,
            "event": MASTER.event,
            "path": ".github/workflows/ci-backend.yml",
            "run_attempt": 1,
            "status": "in_progress",
        }
        self.status_payload: dict[str, object] = {"org_id": ORG, "run_id": RUN, "status": "running", "workflows": []}
        self.workflow_payload: dict[str, object] = {
            "org_id": ORG,
            "run": {"run_id": RUN, "repo": MASTER.repository, "trigger": "workflow_dispatch", "sha": "b" * 40},
            "workflow": {"workflow_id": WORKFLOW, "workflow_path": "ci-backend.yml", "status": "running"},
            "jobs": [],
        }
        self.artifacts: list[dict[str, object]] = []
        self.artifact_payloads: dict[str, bytes] = {}

    def upload(self, name: str, filename: str, payload: str) -> None:
        artifact_id = len(self.receipts) + 1
        body = zipped(filename, payload)
        self.downloads[artifact_id] = body
        self.receipts.append({"id": artifact_id, "name": name, "expired": False, "size_in_bytes": len(body)})

    def ready(self) -> None:
        self.status_payload["workflows"] = [{"workflow_id": WORKFLOW, "workflow_path": "ci-backend.yml"}]

    def finished(self, *, state: str = "finished", gate: str = "finished") -> None:
        self.workflow_payload["workflow"] = {
            "workflow_id": WORKFLOW,
            "workflow_path": "ci-backend.yml",
            "status": state,
        }
        self.workflow_payload["jobs"] = [
            {"job_id": "gatejob", "job_key": "ci-backend.yml:django_tests", "status": gate, "attempts": []},
            {
                "job_id": "schemajob",
                "job_key": "ci-backend.yml:check-migrations",
                "status": "finished",
                "attempts": [{"attempt": 1, "attempt_id": "schemaattempt"}],
            },
        ]

    def artifact(self, *, name: str = "migrated-schema", attempt_id: str = "schemaattempt") -> None:
        artifact_id = f"artifact{len(self.artifacts)}"
        self.artifacts.append(
            {
                "artifact_id": artifact_id,
                "run_id": RUN,
                "workflow_id": WORKFLOW,
                "job_id": "schemajob",
                "attempt_id": attempt_id,
                "name": name,
                "size_bytes": 32,
            }
        )
        self.artifact_payloads[artifact_id] = zipped("schema.dump", "invented schema")

    def run(self, arguments: Sequence[str], *, timeout: int = 60) -> bytes:
        args = list(arguments)
        self.calls.append(args)
        response: object
        if args[:2] == ["gh", "api"]:
            path = args[2]
            if path.endswith("/zip"):
                return self.downloads[int(path.split("/")[-2])]
            if "/artifacts?" in path:
                page = int(path.rsplit("page=", 1)[-1])
                response = {"artifacts": self.receipts[(page - 1) * 100 : page * 100]}
            else:
                response = self.run_payload
        elif args[:3] == ["depot", "ci", "dispatch"]:
            if self.dispatch_failure:
                raise RuntimeError("Dispatch transport failed")
            response = {"org_id": ORG, "run_id": RUN}
        elif args[:3] == ["depot", "ci", "status"]:
            response = self.status_payload
        elif args[:4] == ["depot", "ci", "workflow", "show"]:
            response = self.workflow_payload
        elif args[:4] == ["depot", "ci", "artifacts", "list"]:
            response = {"artifacts": self.artifacts}
        elif args[:4] == ["depot", "ci", "artifacts", "download"]:
            Path(args[args.index("--output-file") + 1]).write_bytes(self.artifact_payloads[args[4]])
            return b""
        else:
            raise AssertionError(f"Unexpected command: {args}")
        return json.dumps(response).encode()


def controller(tmp_path: Path, commands: FakeCommands) -> MasterController:
    return MasterController(
        store=GitHubReceipts(master=MASTER, commands=commands), organization_id=ORG, directory=tmp_path / "receipts"
    )


def persist_owner(commands: FakeCommands, *, engine: Engine = "depot") -> OwnerReceipt:
    owner = OwnerReceipt(master=MASTER, engine=engine)
    commands.upload(OWNER_ARTIFACT, "owner.json", owner.to_json())
    return owner


def persist_handoff(commands: FakeCommands) -> OwnerReceipt:
    owner = persist_owner(commands)
    dispatch = DispatchReceipt(owner_digest=owner.digest, organization_id=ORG, run_id=RUN)
    commands.upload(DISPATCH_ARTIFACT, "dispatch.json", dispatch.to_json())
    binding = DepotBinding(owner_digest=owner.digest, organization_id=ORG, workflow_id=WORKFLOW)
    commands.upload(BINDING_ARTIFACT, "binding.json", binding.to_json())
    commands.ready()
    return owner


@pytest.mark.parametrize("mode", ["", "github", "schedule"])
def test_cli_default_lane_needs_no_depot_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    commands = FakeCommands()
    monkeypatch.setattr(Commands, "run", commands.run)
    for name, value in {
        "GITHUB_REPOSITORY": MASTER.repository,
        "GITHUB_RUN_ID": str(MASTER.github_run_id),
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SHA": MASTER.sha,
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_OUTPUT": str(tmp_path / "outputs"),
        "MASTER_LANE_MODE": mode,
    }.items():
        monkeypatch.setenv(name, value)
    for name in ("DEPOT_ORG_ID", "DEPOT_TOKEN", "MASTER_RUN_ID", "MASTER_SHA", "MASTER_EVENT", "MASTER_SCHEDULE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("sys.argv", ["controller", "select", "--directory", str(tmp_path / "receipts")])
    assert main() == 0
    assert (tmp_path / "outputs").read_text() == "engine=github\nowner_exists=false\n"
    assert all(call[0] == "gh" for call in commands.calls)


def test_publish_acknowledgment_before_binding_and_reuse_it_after_a_flip(tmp_path: Path) -> None:
    commands = FakeCommands()
    control = controller(tmp_path, commands)
    assert control.select(mode="all", run_attempt=1) == {"engine": "depot", "owner_exists": "false"}
    with pytest.raises(ValueError, match="Persist a Depot owner"):
        control.dispatch(run_attempt=1)
    commands.upload(OWNER_ARTIFACT, "owner.json", (control.directory / "owner.json").read_text())
    assert control.dispatch(run_attempt=1) == {"dispatch_exists": "false", "depot_run_id": RUN}
    with pytest.raises(ValueError, match="Persist the dispatch"):
        control.bind()
    commands.upload(DISPATCH_ARTIFACT, "dispatch.json", (control.directory / "dispatch.json").read_text())
    assert control.bind() is None
    commands.ready()
    assert control.bind() == {"binding_exists": "false", "depot_workflow_id": WORKFLOW}
    commands.upload(BINDING_ARTIFACT, "binding.json", (control.directory / "binding.json").read_text())
    commands.run_payload["run_attempt"] = 2
    assert control.select(mode="github", run_attempt=2)["engine"] == "depot"
    assert control.dispatch(run_attempt=2)["dispatch_exists"] == "true"
    resumed = control.bind()
    assert resumed is not None
    assert resumed["binding_exists"] == "true"
    dispatches = [call for call in commands.calls if call[:3] == ["depot", "ci", "dispatch"]]
    assert len(dispatches) == 1
    assert ["--ref", "master"] == dispatches[0][dispatches[0].index("--ref") : dispatches[0].index("--ref") + 2]
    assert f"master_sha={MASTER.sha}" in dispatches[0]


@pytest.mark.parametrize(
    "engine,transport_failure", [(None, False), ("github", False), ("depot", False), ("depot", True)]
)
def test_missing_dispatch_acknowledgment_never_causes_a_second_dispatch(
    tmp_path: Path, engine: Engine | None, transport_failure: bool
) -> None:
    commands = FakeCommands()
    if engine is not None:
        persist_owner(commands, engine=engine)
    if transport_failure:
        commands.dispatch_failure = True
        with pytest.raises(RuntimeError, match="transport failed"):
            controller(tmp_path, commands).dispatch(run_attempt=1)
    commands.run_payload["run_attempt"] = 2
    with pytest.raises(ValueError):
        controller(tmp_path, commands).dispatch(run_attempt=2)
    assert sum(call[:3] == ["depot", "ci", "dispatch"] for call in commands.calls) == int(transport_failure)


@pytest.mark.parametrize(
    "field,value",
    [
        ("head_sha", "b" * 40),
        ("head_branch", "feature"),
        ("event", "pull_request"),
        ("path", ".github/workflows/other.yml"),
        ("repository", {"full_name": "example/other"}),
        ("run_attempt", 2),
        ("status", "completed"),
    ],
)
def test_only_the_active_canonical_run_can_dispatch(tmp_path: Path, field: str, value: object) -> None:
    commands = FakeCommands()
    persist_owner(commands)
    commands.run_payload[field] = value
    with pytest.raises(ValueError):
        controller(tmp_path, commands).dispatch(run_attempt=1)
    assert not any(call[:3] == ["depot", "ci", "dispatch"] for call in commands.calls)


@pytest.mark.parametrize("problem", ["expired", "duplicate", "oversized", "wrong-file", "different-owner"])
def test_unreadable_receipts_cannot_choose_a_new_owner(tmp_path: Path, problem: str) -> None:
    commands = FakeCommands()
    owner = persist_owner(commands)
    if problem == "expired":
        commands.receipts[0]["expired"] = True
    elif problem == "duplicate":
        commands.upload(OWNER_ARTIFACT, "owner.json", owner.to_json())
    elif problem == "oversized":
        commands.receipts[0]["size_in_bytes"] = 65537
    elif problem == "wrong-file":
        commands.downloads[1] = zipped("elsewhere/owner.json", owner.to_json())
    else:
        commands.downloads[1] = zipped(
            "owner.json", replace(owner, master=replace(MASTER, github_run_id=102)).to_json()
        )
    with pytest.raises(ValueError):
        controller(tmp_path, commands).select(mode="github", run_attempt=1)


def test_receipt_lookup_paginates_past_unrelated_artifacts(tmp_path: Path) -> None:
    commands = FakeCommands()
    for index in range(100):
        commands.upload(f"unrelated-{index}", "ignored", "invented")
    persist_owner(commands)
    assert controller(tmp_path, commands).select(mode="github", run_attempt=1)["engine"] == "depot"


def test_cli_authorizes_pinned_inputs_with_the_shared_depot_identifier_grammar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = FakeCommands()
    persist_handoff(commands)
    monkeypatch.setattr(Commands, "run", commands.run)
    for name, value in {
        "GITHUB_REPOSITORY": MASTER.repository,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_SHA": "b" * 40,
        "GITHUB_OUTPUT": str(tmp_path / "outputs"),
        "MASTER_RUN_ID": str(MASTER.github_run_id),
        "MASTER_SHA": MASTER.sha,
        "MASTER_EVENT": MASTER.event,
        "MASTER_SCHEDULE": "",
        "DEPOT_ORG_ID": ORG,
        "DEPOT_JOB_URL": f"https://depot.dev/orgs/{ORG}/workflows/{WORKFLOW}?job=authorize",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr("sys.argv", ["controller", "authorize", "--directory", str(tmp_path / "receipts")])
    assert main() == 0
    assert f"sha={MASTER.sha}\n" in (tmp_path / "outputs").read_text()
    assert "handed_off=true\n" in (tmp_path / "outputs").read_text()


def test_worker_waits_for_binding_and_rejects_another_workflow(tmp_path: Path) -> None:
    commands = FakeCommands()
    control = controller(tmp_path, commands)
    persist_owner(commands)
    assert control.authorize(organization_id=ORG, workflow_id=WORKFLOW) is None
    commands = FakeCommands()
    persist_handoff(commands)
    control = controller(tmp_path, commands)
    with pytest.raises(ValueError, match="not the bound owner"):
        control.authorize(organization_id=ORG, workflow_id="anotherworkflow")
    result = control.authorize(organization_id=ORG, workflow_id=WORKFLOW)
    assert result == {"sha": MASTER.sha, "event": "push", "schedule": "", "handed_off": "true"}


@pytest.mark.parametrize(
    "state,gate,verdict",
    [
        ("finished", "finished", "success"),
        ("finished", "skipped", "failure"),
        ("finished", "cancelled", "failure"),
        ("cancelled", "finished", "failure"),
        ("failed", "finished", "failure"),
    ],
)
def test_relay_requires_a_real_gate_and_keeps_artifacts_on_failure(
    tmp_path: Path, state: str, gate: str, verdict: str
) -> None:
    commands = FakeCommands()
    persist_handoff(commands)
    commands.finished(state=state, gate=gate)
    commands.artifact()
    result = controller(tmp_path, commands).relay(destination=tmp_path / "artifacts")
    assert result is not None
    assert result["verdict"] == verdict
    assert json.loads(result["artifacts"])[0]["name"] == "migrated-schema"
    assert (tmp_path / "artifacts/migrated-schema/schema.dump").read_text() == "invented schema"


def test_relay_polls_depot_without_repeated_github_reads(tmp_path: Path) -> None:
    commands = FakeCommands()
    persist_handoff(commands)
    control = controller(tmp_path, commands)
    assert control.relay(destination=tmp_path / "artifacts") is None
    github_reads = sum(call[0] == "gh" for call in commands.calls)
    assert control.relay(destination=tmp_path / "artifacts") is None
    commands.finished()
    assert control.relay(destination=tmp_path / "artifacts") is not None
    assert sum(call[0] == "gh" for call in commands.calls) == github_reads


def test_artifacts_follow_each_jobs_latest_attempt(tmp_path: Path) -> None:
    commands = FakeCommands()
    persist_handoff(commands)
    commands.finished()
    commands.artifact(attempt_id="oldattempt")
    commands.artifact()
    result = controller(tmp_path, commands).relay(destination=tmp_path / "artifacts")
    assert result is not None
    assert len(json.loads(result["artifacts"])) == 1
    downloads = [call for call in commands.calls if call[:4] == ["depot", "ci", "artifacts", "download"]]
    assert len(downloads) == 1
    assert downloads[0][4] == "artifact1"


@pytest.mark.parametrize(
    "problem", ["different-run", "different-workflow", "unknown-job", "duplicate-name", "unsafe-name"]
)
def test_relay_does_not_download_ambiguous_or_foreign_artifacts(tmp_path: Path, problem: str) -> None:
    commands = FakeCommands()
    persist_handoff(commands)
    commands.finished()
    commands.artifact()
    if problem == "different-run":
        commands.artifacts[0]["run_id"] = "anotherrun"
    elif problem == "different-workflow":
        commands.artifacts[0]["workflow_id"] = "anotherworkflow"
    elif problem == "unknown-job":
        commands.artifacts[0]["job_id"] = "otherjob"
    elif problem == "duplicate-name":
        commands.artifact()
    else:
        commands.artifacts[0]["name"] = "../escape"
    with pytest.raises(ValueError):
        controller(tmp_path, commands).relay(destination=tmp_path / "artifacts")
    assert not any(call[:4] == ["depot", "ci", "artifacts", "download"] for call in commands.calls)
