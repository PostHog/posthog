from django.test import SimpleTestCase

from products.conversations.backend.ai.human_outcome import classify_human_outcome


class TestClassifyHumanOutcome(SimpleTestCase):
    def test_identical_reply_is_used(self):
        draft = "Add the snippet to the head of every page."
        assert classify_human_outcome(draft, draft) == "used"

    def test_whitespace_only_change_is_used(self):
        assert classify_human_outcome("Hello there.", "Hello there.  ") == "used"

    def test_partial_rewrite_is_edited(self):
        draft = "Add the SDK snippet to the head of every page, then reload to send a pageview."
        reply = "Drop the recorder snippet on checkout only, then hard-refresh to send a pageview."
        assert classify_human_outcome(draft, reply) == "edited"

    def test_unrelated_reply_is_ignored(self):
        assert (
            classify_human_outcome(
                "Add the snippet to the head of every page.",
                "We migrated this org to a new plan yesterday.",
            )
            == "ignored"
        )
