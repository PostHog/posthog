from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.github.merge_queue import MergeQueueState

TRUNK = {"login": "trunk-io[bot]", "type": "Bot"}
LINK = "https://app.trunk.io/example-org/merge-queue/repo-id/4242"


def trunk_comment(body: str) -> dict[str, Any]:
    return {"user": TRUNK, "body": body}


class TestMergeQueueState(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "pushed_to",
                f"🚫 This pull request was removed from the merge queue because it was pushed to by @someone. [details]({LINK})",
                MergeQueueState.EJECTED,
            ),
            (
                "failed_tests",
                f"❌ This pull request was removed from the merge queue because it failed tests. [details]({LINK})",
                MergeQueueState.FAILED,
            ),
            (
                "other_removal",
                f"🚫 This pull request was removed from the merge queue. [details]({LINK})",
                MergeQueueState.CANCELLED,
            ),
            (
                "pending_failure",
                f"⚠️ The required check `Backend CI` (Failure) has failed. Pull request failed tests and is waiting for other pull requests to finish testing. [details]({LINK})",
                MergeQueueState.PENDING_FAILURE,
            ),
            (
                "testing",
                f"🧪 Running tests on this pull request (testing on PR #4300). [details]({LINK})",
                MergeQueueState.TESTING,
            ),
            (
                "waiting",
                f"⏳ Waiting to start tests on this pull request because a pull request (#4299) ahead of it failed tests. [details]({LINK})",
                MergeQueueState.QUEUED,
            ),
            (
                "submitted",
                f"✨ Submitted to Merge by @someone. It will be added to the merge queue once all branch protection rules pass. [details]({LINK})",
                MergeQueueState.NOT_READY,
            ),
            ("merged", f"😎 Merged successfully - [details]({LINK})", MergeQueueState.MERGED),
            (
                "instruction_unticked",
                "<!-- Trunk Merge -->\n<!-- Start PR Submit Checkbox -->\n- [ ] <!-- End PR Submit Checkbox -->To merge this pull request, check the box or comment `/trunk merge` below.",
                MergeQueueState.NOT_SUBMITTED,
            ),
            (
                "instruction_ticked",
                "<!-- Trunk Merge -->\n<!-- Start PR Submit Checkbox -->\n- [x] <!-- End PR Submit Checkbox -->To merge this pull request, check the box or comment `/trunk merge` below.",
                MergeQueueState.QUEUED,
            ),
        ]
    )
    def test_reads_state_from_trunk_comment(self, _name: str, body: str, expected: MergeQueueState) -> None:
        assert MergeQueueState.from_comments([trunk_comment(body)]) == expected

    @parameterized.expand(
        [
            (
                "flaky_test_report",
                [
                    trunk_comment(
                        "<!-- Trunk Test Analytics -->\n2 failed tests. https://app.trunk.io/example-org/flaky-tests/pr/4242"
                    )
                ],
            ),
            (
                "person_quoting_trunk",
                [{"user": {"login": "someone"}, "body": f"Running tests on this pull request, see {LINK}"}],
            ),
            ("no_trunk_comment", [{"user": {"login": "someone"}, "body": "LGTM"}]),
            (
                "lookalike_account",
                [{"user": {"login": "trunk-io-fan", "type": "User"}, "body": f"😎 Merged successfully - {LINK}"}],
            ),
            ("missing_user", [{"body": f"😎 Merged successfully - {LINK}"}]),
        ]
    )
    def test_ignores_comments_that_are_not_the_queue_comment(self, _name: str, comments: list[dict[str, Any]]) -> None:
        assert MergeQueueState.from_comments(comments) is None

    def test_unrecognized_latest_comment_fails_closed(self) -> None:
        comments = [
            trunk_comment(f"🧪 Running tests on this pull request. [details]({LINK})"),
            trunk_comment(f"🆕 A wording this reader has never seen. [details]({LINK})"),
        ]
        state = MergeQueueState.from_comments(comments)
        assert state == MergeQueueState.UNKNOWN
        assert state.holds_pull_request and state.push_would_eject

    def test_last_trunk_comment_wins(self) -> None:
        comments = [
            trunk_comment(f"😎 Merged successfully - [details]({LINK})"),
            trunk_comment(f"🧪 Running tests on this pull request. [details]({LINK})"),
        ]
        assert MergeQueueState.from_comments(comments) == MergeQueueState.TESTING

    @parameterized.expand(
        [
            (MergeQueueState.NOT_READY, True, False),
            (MergeQueueState.QUEUED, True, True),
            (MergeQueueState.PENDING_FAILURE, True, True),
            (MergeQueueState.EJECTED, False, False),
            (MergeQueueState.MERGED, False, False),
        ]
    )
    def test_push_guards(self, state: MergeQueueState, holds: bool, push_ejects: bool) -> None:
        assert state.holds_pull_request is holds
        assert state.push_would_eject is push_ejects
