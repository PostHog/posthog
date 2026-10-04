import json
from dataclasses import replace

import pytest

from ci_backend_master_receipts import DepotBinding, Engine, MasterEvent, MasterLane, OwnerReceipt

SHA = "a" * 40
CRON = "23 */3 * * *"
MASTER = MasterEvent(repository="example/repo", github_run_id=101, sha=SHA, event="push")


@pytest.mark.parametrize(
    "event,mode,engine",
    [
        ("push", "", "github"),
        ("schedule", "", "github"),
        ("push", "github", "github"),
        ("schedule", "github", "github"),
        ("push", "schedule", "github"),
        ("schedule", "schedule", "depot"),
        ("push", "all", "depot"),
        ("schedule", "all", "depot"),
    ],
)
def test_first_attempt_selects_the_engine_once(event: MasterLane, mode: str, engine: Engine) -> None:
    master = replace(MASTER, event=event, schedule=CRON if event == "schedule" else "")
    owner = OwnerReceipt.choose(master=master, mode=mode, run_attempt=1, existing=None)
    assert owner.engine == engine
    assert OwnerReceipt.from_json(owner.to_json()) == owner


@pytest.mark.parametrize("mode", ["", "github", "schedule", "all", "invalid"])
@pytest.mark.parametrize("engine", ["github", "depot"])
def test_existing_receipt_survives_rollbacks_and_retries(mode: str, engine: Engine) -> None:
    owner = OwnerReceipt(master=MASTER, engine=engine)
    assert OwnerReceipt.choose(master=MASTER, mode=mode, run_attempt=2, existing=owner) == owner


@pytest.mark.parametrize("attempt", [0, True, 2, 3])
def test_missing_receipt_cannot_reroute_a_rerun(attempt: int) -> None:
    with pytest.raises(ValueError):
        OwnerReceipt.choose(master=MASTER, mode="all", run_attempt=attempt, existing=None)


def test_invalid_mode_cannot_start_an_engine() -> None:
    with pytest.raises(ValueError, match="mode"):
        OwnerReceipt.choose(master=MASTER, mode="depot", run_attempt=1, existing=None)


@pytest.mark.parametrize(
    "master",
    [
        replace(MASTER, github_run_id=102),
        replace(MASTER, sha="b" * 40),
        replace(MASTER, repository="example/another-repo"),
        replace(MASTER, event="schedule", schedule=CRON),
    ],
)
def test_same_commit_cannot_reuse_another_events_owner(master: MasterEvent) -> None:
    with pytest.raises(ValueError, match="another event"):
        OwnerReceipt.choose(
            master=master, mode="all", run_attempt=1, existing=OwnerReceipt(master=MASTER, engine="github")
        )


def test_schedules_at_the_same_sha_keep_separate_identities() -> None:
    first = replace(MASTER, event="schedule", schedule=CRON)
    second = replace(first, github_run_id=102)
    alternate_cron = replace(first, schedule="23 1 * * *")
    owner = OwnerReceipt(master=first, engine="depot")
    for master in (second, alternate_cron):
        with pytest.raises(ValueError, match="another event"):
            OwnerReceipt.choose(master=master, mode="github", run_attempt=1, existing=owner)


@pytest.mark.parametrize(
    "field,value",
    [
        ("github_run_id", True),
        ("github_run_id", "101"),
        ("github_run_id", 0),
        ("sha", "master"),
        ("ref", "refs/heads/feature"),
        ("repository", "../repo"),
        ("event", "pull_request"),
        ("event", "workflow_dispatch"),
        ("event", "schedule"),
        ("schedule", CRON),
        ("engine", "both"),
        ("version", True),
        ("version", 2),
        ("unexpected", "field"),
    ],
)
def test_receipts_reject_other_events_and_malformed_records(field: str, value: object) -> None:
    payload = json.loads(OwnerReceipt(master=MASTER, engine="depot").to_json())
    payload[field] = value
    with pytest.raises(ValueError):
        OwnerReceipt.from_json(json.dumps(payload))


def test_receipts_reject_incomplete_or_oversized_records() -> None:
    for payload in ("{}", "[]", "x" * 4097):
        with pytest.raises(ValueError):
            OwnerReceipt.from_json(payload)


def binding(owner: OwnerReceipt) -> DepotBinding:
    return DepotBinding(owner_digest=owner.digest, organization_id="exampleorg", workflow_id="exampleworkflow")


def test_only_the_bound_depot_workflow_can_run_the_pinned_event() -> None:
    owner = OwnerReceipt(master=MASTER, engine="depot")
    restored = DepotBinding.from_json(binding(owner).to_json())
    restored.authorize(owner=owner, master=MASTER, organization_id="exampleorg", workflow_id="exampleworkflow")


@pytest.mark.parametrize("change", ["engine", "sha", "event", "receipt", "organization", "workflow"])
def test_bound_workflow_rejects_a_different_owner_or_dispatch(change: str) -> None:
    owner = OwnerReceipt(master=MASTER, engine="depot")
    original = binding(owner)
    master = MASTER
    organization_id = "exampleorg"
    workflow_id = "exampleworkflow"
    if change == "engine":
        owner = replace(owner, engine="github")
    elif change == "sha":
        master = replace(master, sha="b" * 40)
    elif change == "event":
        master = replace(master, github_run_id=102)
    elif change == "receipt":
        owner = replace(owner, master=replace(master, github_run_id=102))
        master = owner.master
    elif change == "organization":
        organization_id = "otherorg"
    elif change == "workflow":
        workflow_id = "otherworkflow"
    with pytest.raises(ValueError):
        original.authorize(owner=owner, master=master, organization_id=organization_id, workflow_id=workflow_id)


def test_resume_reuses_a_binding_instead_of_dispatching_again() -> None:
    owner = OwnerReceipt(master=MASTER, engine="depot")
    existing = binding(owner)
    assert DepotBinding.resume(owner=owner, existing=existing, run_attempt=2) == existing
    assert DepotBinding.resume(owner=owner, existing=None, run_attempt=1) is None
    with pytest.raises(ValueError, match="outcome is unknown"):
        DepotBinding.resume(owner=owner, existing=None, run_attempt=2)
    with pytest.raises(ValueError, match="another owner"):
        DepotBinding.resume(
            owner=replace(owner, master=replace(MASTER, github_run_id=102)), existing=existing, run_attempt=2
        )
    with pytest.raises(ValueError, match="GitHub owns"):
        DepotBinding.resume(owner=replace(owner, engine="github"), existing=None, run_attempt=1)


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner_digest", "a" * 40),
        ("organization_id", "../org"),
        ("workflow_id", "workflow/id"),
        ("workflow_id", ""),
        ("version", 2),
        ("unexpected", "field"),
    ],
)
def test_malformed_bindings_cannot_authorize_a_workflow(field: str, value: object) -> None:
    payload = json.loads(binding(OwnerReceipt(master=MASTER, engine="depot")).to_json())
    payload[field] = value
    with pytest.raises(ValueError):
        DepotBinding.from_json(json.dumps(payload))
