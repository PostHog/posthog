from __future__ import annotations

import os
import re
import sys
import subprocess
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).with_name("check_call_assertions.py")


def diff_for(path: str, *lines: str) -> str:
    header = (
        f"diff --git a/{path} b/{path}\nindex 0000000..1111111 100644\n--- a/{path}\n+++ b/{path}\n@@ -1,0 +1,9 @@\n"
    )
    return header + "".join(f"{line}\n" for line in lines)


def run_check(diff: str, tmp_path: Path) -> dict[str, str]:
    output_file = tmp_path / "github_output"
    output_file.write_text("")
    subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        input=diff,
        text=True,
        check=True,
        capture_output=True,
        env={**os.environ, "GITHUB_OUTPUT": str(output_file)},
    )
    raw = output_file.read_text()
    outputs = dict(re.findall(r"^(status|summary)=(.*)$", raw, re.MULTILINE))
    body = re.search(r"^body<<(\S+)\n(.*)\n\1$", raw, re.MULTILINE | re.DOTALL)
    assert body is not None
    outputs["body"] = body.group(2)
    return outputs


@pytest.mark.parametrize(
    "diff,expected_status,expected_summary",
    [
        pytest.param(
            diff_for(
                "frontend/src/lib/thing.test.ts",
                "+    expect(onSave).toHaveBeenCalledWith({ id: 1 })",
                "+    expect(onSave).not.toHaveBeenCalled()",
                "+    expect(onSave).toHaveBeenNthCalledWith(2, 'b')",
                "+    expect(onSave).toHaveBeenLastCalledWith('c')",
                "+    expect(fetchMock).toBeCalledTimes(1)",
                "+    const [[request]] = fetchMock.mock.calls",
                "+    await fetchMock.mock.results[0].value",
                "+    expect(screen.getByText('Saved')).toBeInTheDocument()",
            ),
            "warn",
            "7 added test lines assert on mock calls (Δ +7 vs base)",
            id="jest-call-assertions-count-and-outcome-assertions-do-not",
        ),
        pytest.param(
            diff_for(
                "posthog/api/test/test_thing.py",
                "+        send.assert_called_once_with(team_id=1)",
                "+        send.assert_called()",
                "+        send.assert_has_calls([call(1)])",
                "+        send.assert_not_called()",
                "+        send.assert_any_call(1)",
                "+        assert send.call_args.kwargs['team_id'] == 1",
                "+        assert send.call_args_list == []",
                "+        assert send.call_count == 2",
                "+        assert send.mock_calls == []",
                "+        assert response.status_code == 200",
            ),
            "warn",
            "9 added test lines assert on mock calls (Δ +9 vs base)",
            id="python-call-assertions-count-and-outcome-assertions-do-not",
        ),
        pytest.param(
            diff_for("posthog/tasks/thing.py", "+    send.assert_called_once()")
            + diff_for("frontend/src/lib/thing.ts", "+    expect(onSave).toHaveBeenCalled()")
            + diff_for("docs/testing.md", "+Avoid `toHaveBeenCalled` where you can."),
            "ok",
            "0 added test lines assert on mock calls (Δ +0 vs base)",
            id="files-that-are-not-tests-are-ignored",
        ),
        pytest.param(
            diff_for("products/x/backend/tests/test_api.py", "+    send.assert_called_once()")
            + diff_for("products/x/frontend/__tests__/logic.ts", "+    expect(a).toHaveBeenCalled()")
            + diff_for("nodejs/src/cdp/thing.spec.ts", "+    expect(b).toHaveBeenCalled()")
            + diff_for("posthog/conftest.py", "+    assert send.call_count == 1")
            + diff_for("ee/billing/thing_test.py", "+    send.assert_called()")
            + diff_for("products/x/stats/tests.py", "+    send.assert_called()")
            + 'diff --git "a/posthog/test/test_\\303\\251.py" "b/posthog/test/test_\\303\\251.py"\n'
            + "@@ -0,0 +1 @@\n+    send.assert_called()\n",
            "warn",
            "7 added test lines assert on mock calls (Δ +7 vs base)",
            id="every-test-file-layout-is-measured",
        ),
        pytest.param(
            diff_for(
                "posthog/api/test/test_thing.py",
                "-        send.assert_called_once_with(team_id=1)",
                "+        send.assert_called_once_with(team_id=2)",
                "         send.assert_not_called()",
            ),
            "ok",
            "1 added test line asserts on mock calls (Δ +0 vs base)",
            id="an-edited-call-assertion-is-no-increase",
        ),
        pytest.param(
            diff_for(
                "posthog/api/test/test_thing.py",
                "-        send.assert_called_once()",
                "-        send.assert_called_once()",
                "+        send.assert_called_once()",
            ),
            "ok",
            "1 added test line asserts on mock calls (Δ -1 vs base)",
            id="removing-more-than-adding-is-ok",
        ),
    ],
)
def test_warns_only_when_a_pr_adds_more_call_assertions_than_it_removes(
    diff: str, expected_status: str, expected_summary: str, tmp_path: Path
) -> None:
    outputs = run_check(diff, tmp_path)
    assert (outputs["status"], outputs["summary"]) == (expected_status, expected_summary)


def test_body_lists_files_with_the_most_added_call_assertions_first(tmp_path: Path) -> None:
    diff = diff_for("posthog/test/test_a.py", "+    a.assert_called()", "-    a.assert_not_called()") + diff_for(
        "frontend/src/b.test.ts", "+    expect(b).toHaveBeenCalled()", "+    expect(b).toHaveBeenCalledTimes(2)"
    )
    body = run_check(diff, tmp_path)["body"]
    assert body.index("| `frontend/src/b.test.ts` | 2 | +2 |") < body.index("| `posthog/test/test_a.py` | 1 | +0 |")


def test_body_keeps_hostile_file_paths_inert(tmp_path: Path) -> None:
    body = run_check(diff_for("posthog/test/test_x`|@user|`y.py", "+    a.assert_called()"), tmp_path)["body"]
    assert "| `posthog/test/test_x@usery.py` | 1 | +1 |" in body
    assert "`|" not in body
