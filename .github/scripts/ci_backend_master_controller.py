import os
import re
import sys
import json
import time
import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ci_backend_master_depot import DepotMaster, DispatchReceipt
from ci_backend_master_receipts import DEPOT_IDENTIFIER_PATTERN, DepotBinding, MasterEvent, MasterLane, OwnerReceipt
from ci_backend_master_store import BINDING_ARTIFACT, DISPATCH_ARTIFACT, OWNER_ARTIFACT, Commands, GitHubReceipts


@dataclass(frozen=True, kw_only=True, slots=True)
class Handoff:
    owner: OwnerReceipt
    dispatch: DispatchReceipt
    binding: DepotBinding


class MasterController:
    def __init__(self, *, store: GitHubReceipts, organization_id: str, directory: Path) -> None:
        self.store = store
        self.organization_id = organization_id
        self.directory = directory
        self._handoff: Handoff | None = None

    def save(self, filename: str, payload: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / filename).write_text(payload, encoding="utf-8")

    def select(self, *, mode: str, run_attempt: int) -> dict[str, str]:
        self.store.validate_run(run_attempt=run_attempt)
        payloads = self.store.read([OWNER_ARTIFACT])
        existing = self.store.owner(payloads=payloads)
        owner = OwnerReceipt.choose(master=self.store.master, mode=mode, run_attempt=run_attempt, existing=existing)
        self.save("owner.json", owner.to_json())
        return {"engine": owner.engine, "owner_exists": str(existing is not None).lower()}

    def load(self) -> dict[str, str]:
        self.store.validate_run()
        return self.store.read([OWNER_ARTIFACT, DISPATCH_ARTIFACT, BINDING_ARTIFACT])

    def owner(self, payloads: dict[str, str]) -> OwnerReceipt:
        owner = self.store.owner(payloads=payloads)
        if owner is None or owner.engine != "depot":
            raise ValueError("Persist a Depot owner receipt in the canonical run before dispatching")
        return owner

    def acknowledged(self, *, owner: OwnerReceipt, payloads: dict[str, str]) -> DispatchReceipt:
        payload = payloads.get(DISPATCH_ARTIFACT)
        if payload is None:
            raise ValueError("Persist the dispatch receipt before binding a Depot workflow")
        dispatch = DispatchReceipt.from_json(payload)
        dispatch.validate(owner=owner, organization_id=self.organization_id)
        return dispatch

    def depot(self, owner: OwnerReceipt) -> DepotMaster:
        return DepotMaster(owner=owner, organization_id=self.organization_id, commands=self.store.commands)

    def dispatch(self, *, run_attempt: int) -> dict[str, str]:
        self.store.validate_run(run_attempt=run_attempt)
        payloads = self.store.read([OWNER_ARTIFACT, DISPATCH_ARTIFACT, BINDING_ARTIFACT])
        owner = self.owner(payloads)
        previous = payloads.get(DISPATCH_ARTIFACT)
        if previous is None and BINDING_ARTIFACT in payloads:
            raise ValueError("Binding has no dispatch receipt; recover the original Depot run")
        existing = DispatchReceipt.from_json(previous) if previous is not None else None
        dispatch = self.depot(owner).dispatch(existing=existing, run_attempt=run_attempt)
        self.save("dispatch.json", dispatch.to_json())
        return {"dispatch_exists": str(existing is not None).lower(), "depot_run_id": dispatch.run_id}

    def bind(self) -> dict[str, str] | None:
        payloads = self.load()
        owner = self.owner(payloads)
        dispatch = self.acknowledged(owner=owner, payloads=payloads)
        existing = self.store.binding(owner=owner, payloads=payloads)
        candidate = self.depot(owner).bind(dispatch=dispatch)
        if candidate is None:
            return None
        if existing is not None and existing != candidate:
            raise ValueError("Do not replace the canonical Depot workflow binding")
        self.save("binding.json", candidate.to_json())
        return {"binding_exists": str(existing is not None).lower(), "depot_workflow_id": candidate.workflow_id}

    def authorize(self, *, organization_id: str, workflow_id: str) -> dict[str, str] | None:
        payloads = self.load()
        owner = self.owner(payloads)
        binding = self.store.binding(owner=owner, payloads=payloads)
        if binding is None:
            return None
        dispatch = self.acknowledged(owner=owner, payloads=payloads)
        binding.authorize(
            owner=owner, master=self.store.master, organization_id=organization_id, workflow_id=workflow_id
        )
        self.depot(owner).workflow(dispatch=dispatch, binding=binding)
        return {
            "sha": owner.master.sha,
            "event": owner.master.event,
            "schedule": owner.master.schedule,
            "handed_off": "true",
        }

    def handoff(self) -> Handoff:
        if self._handoff is None:
            payloads = self.load()
            owner = self.owner(payloads)
            dispatch = self.acknowledged(owner=owner, payloads=payloads)
            binding = self.store.binding(owner=owner, payloads=payloads)
            if binding is None:
                raise ValueError("Canonical run has no Depot workflow binding")
            self._handoff = Handoff(owner=owner, dispatch=dispatch, binding=binding)
        return self._handoff

    def relay(self, *, destination: Path) -> dict[str, str] | None:
        # Receipts are immutable, so polling Depot must not keep spending the GitHub API bucket.
        handoff = self.handoff()
        depot = self.depot(handoff.owner)
        workflow = depot.workflow(dispatch=handoff.dispatch, binding=handoff.binding)
        verdict = depot.verdict(workflow)
        if verdict == "pending":
            return None
        artifacts = depot.collect_artifacts(
            dispatch=handoff.dispatch, binding=handoff.binding, workflow=workflow, destination=destination
        )
        self.save("artifacts.json", json.dumps(artifacts))
        return {
            "verdict": verdict,
            "artifacts": json.dumps(artifacts),
            "depot_workflow_id": handoff.binding.workflow_id,
        }


def outputs(values: dict[str, str]) -> None:
    if any("\n" in value or "\r" in value for value in values.values()):
        raise ValueError("Controller outputs must not contain line breaks")
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        for name, value in values.items():
            output.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["select", "dispatch", "bind", "authorize", "relay"])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--artifact-directory", type=Path)
    parser.add_argument("--timeout", type=int, default=600)
    options = parser.parse_args()
    master = MasterEvent(
        repository=os.environ["GITHUB_REPOSITORY"],
        github_run_id=int(os.environ.get("MASTER_RUN_ID") or os.environ["GITHUB_RUN_ID"]),
        sha=os.environ.get("MASTER_SHA") or os.environ["GITHUB_SHA"],
        event=cast(MasterLane, os.environ.get("MASTER_EVENT") or os.environ["GITHUB_EVENT_NAME"]),
        schedule=os.environ.get("MASTER_SCHEDULE", ""),
    )
    controller = MasterController(
        store=GitHubReceipts(master=master, commands=Commands()),
        organization_id=os.environ.get("DEPOT_ORG_ID", ""),
        directory=options.directory,
    )
    if options.command == "select":
        outputs(
            controller.select(
                mode=os.environ.get("MASTER_LANE_MODE", ""), run_attempt=int(os.environ["GITHUB_RUN_ATTEMPT"])
            )
        )
        return 0
    if options.command == "dispatch":
        outputs(controller.dispatch(run_attempt=int(os.environ["GITHUB_RUN_ATTEMPT"])))
        return 0
    if options.timeout <= 0:
        raise ValueError("Controller timeout must be positive")
    if options.command == "relay" and options.artifact_directory is None:
        raise ValueError("Relay requires an artifact directory")
    job = re.fullmatch(
        rf"https://depot\.dev/orgs/({DEPOT_IDENTIFIER_PATTERN})/workflows/({DEPOT_IDENTIFIER_PATTERN})(?:[/?].*)?",
        os.environ.get("DEPOT_JOB_URL", ""),
    )
    if options.command == "authorize" and job is None:
        raise ValueError("Depot job URL must identify the worker being authorized")
    deadline = time.monotonic() + options.timeout
    while time.monotonic() < deadline:
        if options.command == "bind":
            result = controller.bind()
        elif options.command == "authorize":
            assert job is not None
            result = controller.authorize(organization_id=job[1], workflow_id=job[2])
        else:
            assert options.artifact_directory is not None
            result = controller.relay(destination=options.artifact_directory)
        if result is not None:
            outputs(result)
            return 1 if result.get("verdict") == "failure" else 0
        time.sleep(min(60, max(0, deadline - time.monotonic())))
    raise TimeoutError("Controller timed out; inspect the original Depot run instead of dispatching another")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, TimeoutError, KeyError, OSError) as error:
        # Fixed error messages stay useful without exposing API payloads or subprocess credentials.
        message = str(error).replace("%", "%25").replace("\n", "%0A").replace("\r", "%0D")
        sys.stderr.write(f"::error::{type(error).__name__}: {message}\n")
        sys.exit(1)
