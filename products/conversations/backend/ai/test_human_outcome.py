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

    def test_long_draft_sent_with_a_new_greeting_is_used(self):
        body = (
            "Session recordings can go missing when an ad blocker stops the recorder or when the domain is not "
            "in your authorized domains list. Open Project settings, go to Session replay, and add your domain. "
            "Then check the network tab for a request to the recorder script. If recordings still do not appear, "
            "check that your sampling rate is not zero."
        )
        draft = f"Hi there, thanks for reaching out. {body} Let me know if that helps."
        reply = f"Hey Sam! {body} I looked at your project and the sampling rate is fine. Cheers, Alex"
        assert classify_human_outcome(draft, reply) == "used"

    def test_unrelated_reply_is_ignored(self):
        assert (
            classify_human_outcome(
                "Add the snippet to the head of every page.",
                "We migrated this org to a new plan yesterday.",
            )
            == "ignored"
        )
