from django.test import SimpleTestCase

from parameterized import parameterized

from products.conversations.backend.ai.human_outcome import MAX_SCORED_CHARS, classify_human_outcome

_LONG_DRAFT = (
    "Open Project settings and go to Session replay. Add your domain to the authorized list, "
    "then reload the page and check the network tab for the recorder script. "
) * 70


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

    def test_long_draft_sent_with_a_new_greeting_is_not_ignored(self):
        body = (
            "Session recordings can go missing when an ad blocker stops the recorder or when the domain is not "
            "in your authorized domains list. Open Project settings, go to Session replay, and add your domain. "
            "Then check the network tab for a request to the recorder script. If recordings still do not appear, "
            "check that your sampling rate is not zero."
        )
        draft = f"Hi there, thanks for reaching out. {body} Let me know if that helps."
        reply = f"Hey Sam! {body} I looked at your project and the sampling rate is fine. Cheers, Alex"
        assert classify_human_outcome(draft, reply) == "edited"

    @parameterized.expand(
        [
            ("kept_only_in_part", _LONG_DRAFT[:4000], "edited"),
            ("sent_with_a_new_greeting", f"Hey Sam! {_LONG_DRAFT} Cheers, Alex", "used"),
        ]
    )
    def test_long_draft_is_scored_over_its_whole_text(self, _name, reply, expected):
        assert classify_human_outcome(_LONG_DRAFT, reply) == expected

    def test_texts_past_the_scoring_limit_get_no_outcome(self):
        draft = _LONG_DRAFT * 2
        assert len(draft) > MAX_SCORED_CHARS
        assert classify_human_outcome(draft, f"Hey Sam! {draft}") is None

    @parameterized.expand(
        [
            (
                "chinese",
                "如果会话记录没有显示请在项目设置中确认域名已加入允许列表",
                "如果会话记录没有显示请先在项目设置中确认域名已加入允许列表",
            ),
            (
                "japanese",
                "セッションの記録が表示されない場合は、プロジェクト設定でドメインが許可リストに登録されているか確認してください。",
                "セッションの記録が表示されない場合は、プロジェクト設定でドメインが許可リストに登録されているかご確認ください。",
            ),
        ]
    )
    def test_one_character_edit_without_word_spaces_is_used(self, _name, draft, reply):
        # A whole sentence in these scripts is one run of word characters, so matching runs of
        # them would leave a lightly edited reply with nothing in common with the draft.
        assert classify_human_outcome(draft, reply) == "used"

    def test_unrelated_reply_is_ignored(self):
        assert (
            classify_human_outcome(
                "Add the snippet to the head of every page.",
                "We migrated this org to a new plan yesterday.",
            )
            == "ignored"
        )
