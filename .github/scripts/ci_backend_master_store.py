import io
import json
import zipfile
import subprocess
from collections.abc import Sequence
from typing import cast

from ci_backend_master_receipts import DepotBinding, MasterEvent, OwnerReceipt

OWNER_ARTIFACT = "backend-master-owner"
DISPATCH_ARTIFACT = "backend-master-dispatch"
BINDING_ARTIFACT = "backend-master-depot-binding"
MAX_RECEIPT_BYTES = 4096
MAX_RECEIPT_ZIP_BYTES = 65536


def record(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("API response must be an object")
    return cast(dict[str, object], value)


def records(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("API response must contain a list")
    return [record(item) for item in value]


def integer(value: object) -> int:
    if type(value) is not int or value < 1:
        raise ValueError("API response must contain a positive integer")
    return value


def text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("API response must contain a string")
    return value


class Commands:
    def run(self, arguments: Sequence[str], *, timeout: int = 60) -> bytes:
        try:
            completed = subprocess.run(arguments, capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"{arguments[0]} {arguments[1]} timed out") from None
        if completed.returncode:
            # CLI stderr can include credentials or response payloads. Keep them out of annotations.
            raise RuntimeError(f"{arguments[0]} {arguments[1]} exited with status {completed.returncode}")
        return completed.stdout

    def json(self, arguments: Sequence[str]) -> object:
        return json.loads(self.run(arguments))


class GitHubReceipts:
    def __init__(self, *, master: MasterEvent, commands: Commands) -> None:
        self.master = master
        self.commands = commands

    @property
    def run_path(self) -> str:
        return f"repos/{self.master.repository}/actions/runs/{self.master.github_run_id}"

    def validate_run(self, *, run_attempt: int | None = None) -> None:
        run = record(self.commands.json(["gh", "api", self.run_path]))
        if (
            run.get("id") != self.master.github_run_id
            or record(run.get("repository")).get("full_name") != self.master.repository
            or run.get("path") != ".github/workflows/ci-backend.yml"
            or run.get("head_branch") != "master"
            or run.get("head_sha") != self.master.sha
            or run.get("event") != self.master.event
        ):
            raise ValueError("Receipt source is not this canonical master Backend CI run")
        if run_attempt is not None and (
            integer(run.get("run_attempt")) != run_attempt or run.get("status") != "in_progress"
        ):
            raise ValueError("Only the active canonical GitHub attempt can choose or dispatch an owner")

    def read(self, names: Sequence[str]) -> dict[str, str]:
        selected: dict[str, dict[str, object]] = {}
        seen: set[int] = set()
        for page in range(1, 11):
            listing = record(self.commands.json(["gh", "api", f"{self.run_path}/artifacts?per_page=100&page={page}"]))
            artifacts = records(listing.get("artifacts"))
            for artifact in artifacts:
                artifact_id = integer(artifact.get("id"))
                if artifact_id in seen:
                    raise ValueError("Artifact pagination repeated an artifact; retry the receipt read")
                seen.add(artifact_id)
                name = text(artifact.get("name"))
                if name not in names:
                    continue
                if name in selected:
                    raise ValueError("Canonical run has duplicate receipt artifacts")
                selected[name] = artifact
            if len(artifacts) < 100:
                break
        else:
            raise ValueError("Canonical run exceeds the receipt pagination limit")
        result: dict[str, str] = {}
        for name, artifact in selected.items():
            if artifact.get("expired") is not False:
                raise ValueError("Receipt artifact expired; recover the original owner instead of choosing again")
            if integer(artifact.get("size_in_bytes")) > MAX_RECEIPT_ZIP_BYTES:
                raise ValueError("Receipt artifact exceeds the download limit")
            payload = self.commands.run(
                ["gh", "api", f"repos/{self.master.repository}/actions/artifacts/{integer(artifact['id'])}/zip"]
            )
            if len(payload) > MAX_RECEIPT_ZIP_BYTES:
                raise ValueError("Receipt archive exceeds the download limit")
            filename = {
                OWNER_ARTIFACT: "owner.json",
                DISPATCH_ARTIFACT: "dispatch.json",
                BINDING_ARTIFACT: "binding.json",
            }[name]
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                if archive.namelist() != [filename] or archive.getinfo(filename).file_size > MAX_RECEIPT_BYTES:
                    raise ValueError("Receipt archive has unexpected contents")
                result[name] = archive.read(filename).decode("utf-8")
        return result

    def owner(self, *, payloads: dict[str, str]) -> OwnerReceipt | None:
        payload = payloads.get(OWNER_ARTIFACT)
        if payload is None:
            return None
        owner = OwnerReceipt.from_json(payload)
        if owner.master != self.master:
            raise ValueError("Canonical receipt belongs to a different master event")
        return owner

    def binding(self, *, owner: OwnerReceipt, payloads: dict[str, str]) -> DepotBinding | None:
        payload = payloads.get(BINDING_ARTIFACT)
        if payload is None:
            return None
        binding = DepotBinding.from_json(payload)
        if binding.owner_digest != owner.digest:
            raise ValueError("Canonical Depot binding belongs to a different owner receipt")
        return binding
