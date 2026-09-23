from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import yaml
from owners_yaml.resolver import OWNERS_FILENAME, OwnersResolver, Purpose, team_channel, teams_registry

CONFORMANCE_DIR = Path(__file__).parent.parent / "conformance"
CASE_FILES = sorted((CONFORMANCE_DIR / "cases").glob("*.yaml"))


@dataclass(frozen=True)
class ConformanceCase:
    name: str
    files: dict[str, str]
    purpose: Purpose
    producer: str | None
    expect: dict[str, dict[str, Any]]


def load_cases() -> list[pytest.ParameterSet]:
    params = []
    for case_file in CASE_FILES:
        for raw in yaml.safe_load(case_file.read_text())["cases"]:
            case = ConformanceCase(
                name=raw["name"],
                files=raw["files"],
                purpose=raw.get("purpose", "slack"),
                producer=raw.get("producer"),
                expect=raw["expect"],
            )
            params.append(pytest.param(case, id=f"{case_file.name}::{case.name}"))
    return params


def resolve_channel(case: ConformanceCase, owners: list[str], resolved_slack: str | None) -> str | None:
    if case.producer is None or not owners or owners[0].startswith("@"):
        return resolved_slack
    # OwnersResolver takes no producer, so a producer case looks the channel up with team_channel.
    registry = teams_registry(case.files.get(OWNERS_FILENAME, ""))
    return team_channel(owners[0], registry, case.purpose, case.producer).channel


@pytest.mark.parametrize("case", load_cases())
def test_conformance_case(tmp_path: Path, case: ConformanceCase) -> None:
    for rel, text in case.files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    resolver = OwnersResolver(repo_root=tmp_path, purpose=case.purpose)

    actual = {}
    for path in case.expect:
        resolution = resolver.resolve(path)
        owners = resolution.owners or []
        actual[path] = {
            "owners": owners,
            "unowned_by_design": resolution.unowned_by_design,
            "status": resolution.status,
            "source": resolution.source,
            "slack": resolve_channel(case, owners, resolution.slack),
            "additions": resolution.additions,
        }
    # A case that leaves `additions` out expects none, so the cases written before the field
    # existed also check that nothing leaks into it.
    expected = {path: {"additions": [], **resolution} for path, resolution in case.expect.items()}

    assert actual == expected


@pytest.mark.parametrize("case_file", CASE_FILES, ids=[f.name for f in CASE_FILES])
def test_case_file_matches_schema(case_file: Path) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((CONFORMANCE_DIR / "case.schema.json").read_text())
    document = yaml.safe_load(case_file.read_text())

    jsonschema.validate(document, schema, cls=jsonschema.Draft202012Validator)
    names = [case["name"] for case in document["cases"]]
    assert len(names) == len(set(names)), "case names must be unique within a file"
