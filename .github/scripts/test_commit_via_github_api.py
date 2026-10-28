import base64
import importlib.util
from pathlib import Path
from typing import Any

import pytest

SCRIPT_PATH = Path(__file__).with_name("commit_via_github_api.py")
SPEC = importlib.util.spec_from_file_location("commit_via_github_api", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(script)

TESTED = "a" * 40
MESSAGE = "chore: update OpenAPI generated types"


def head(oid: str, parents: list[str], headline: str = MESSAGE) -> dict[str, Any]:
    return {
        "repository": {
            "ref": {
                "target": {
                    "oid": oid,
                    "messageHeadline": headline,
                    "parents": {"nodes": [{"oid": parent} for parent in parents]},
                }
            }
        }
    }


@pytest.mark.parametrize(
    "branch_head,expected_exit,expected_mutations",
    [
        pytest.param(head(TESTED, ["p" * 40], "feat: the tested change"), 0, 1, id="commits_on_tested_head"),
        pytest.param(head("b" * 40, [TESTED]), 0, 0, id="earlier_attempt_landed"),
        pytest.param(head("b" * 40, [TESTED], "fix: a push during the run"), 1, 0, id="someone_else_pushed"),
        pytest.param(head("b" * 40, [TESTED, "c" * 40]), 1, 0, id="merge_commit_on_top"),
    ],
)
def test_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    branch_head: dict[str, Any],
    expected_exit: int,
    expected_mutations: int,
) -> None:
    monkeypatch.chdir(tmp_path)
    Path("types.ts").write_text("export type A = 1\n")
    mutations: list[dict[str, Any]] = []

    def fake_graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if query is script.BRANCH_HEAD_QUERY:
            return branch_head
        mutations.append(variables["input"])
        return {"createCommitOnBranch": {"commit": {"url": "https://github.com/o/r/commit/new"}}}

    monkeypatch.setattr(script, "graphql", fake_graphql)

    assert script.commit("o/r", "feature", TESTED, MESSAGE, ["types.ts", "removed.ts"]) == expected_exit
    assert len(mutations) == expected_mutations
    if mutations:
        assert mutations[0]["expectedHeadOid"] == TESTED
        assert mutations[0]["fileChanges"] == {
            "additions": [{"path": "types.ts", "contents": base64.b64encode(b"export type A = 1\n").decode()}],
            "deletions": [{"path": "removed.ts"}],
        }
