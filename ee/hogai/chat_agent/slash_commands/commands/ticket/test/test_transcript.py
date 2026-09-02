from unittest import TestCase

from parameterized import parameterized

from posthog.schema import AssistantMessage, HumanMessage

from ee.hogai.chat_agent.slash_commands.commands.ticket.transcript import (
    customer_turns,
    render_transcript,
    strip_unverifiable_quotes,
    unverifiable_quotes,
)

TWO_TURNS = ["the nightly job finished succesfully last week", "the nightly job ran sucessfully again today"]


class TestCustomerTurns(TestCase):
    @parameterized.expand(
        [
            ("bare command carries nothing", "/ticket", []),
            ("command with text keeps the text", "/ticket the sync is failing", ["the sync is failing"]),
            ("plain message is kept", "the sync is failing", ["the sync is failing"]),
            ("word starting with the command is untouched", "/ticketing is broken", ["/ticketing is broken"]),
        ]
    )
    def test_customer_turn_extraction(self, _name, content, expected):
        self.assertEqual(customer_turns([HumanMessage(content=content)]), expected)


class TestRenderTranscript(TestCase):
    def test_tags_each_side_and_drops_what_carries_nothing(self):
        rendered = render_transcript(
            [
                HumanMessage(content="the sync is failing"),
                AssistantMessage(content="Which source?"),
                AssistantMessage(content=""),
                HumanMessage(content="/ticket"),
            ]
        )
        self.assertEqual(
            rendered,
            "<customer>\nthe sync is failing\n</customer>\n<posthog_ai>\nWhich source?\n</posthog_ai>",
        )


class TestStripUnverifiableQuotes(TestCase):
    @parameterized.expand(
        [
            ("exact match is kept", 'They said "the sync is failing" today', True),
            ("collapsed whitespace is kept", 'They said "the  sync is  failing" today', True),
            ("added trailing period is kept", 'They said "the sync is failing." today', True),
            ("nested double quote written as single is kept", "They said \"on the 'Reports' page\" today", True),
            ("changed wording is stripped", 'They said "the sync is broken" today', False),
            ("short span the customer wrote is kept", 'They said "sync" today', True),
            ("short span the customer never wrote is stripped", 'They said "queue" today', False),
            ("recased identifier is stripped", 'They said "$PageView" today', False),
        ]
    )
    def test_cosmetic_drift_survives_but_wording_changes_do_not(self, _name, summary, should_keep):
        turns = ['the sync is failing on the "Reports" page, no $pageview events']
        result = strip_unverifiable_quotes(summary, turns)
        self.assertEqual('"' in result, should_keep)

    def test_quote_assembled_from_two_messages_is_stripped(self):
        summary = 'The customer said it finished "succesfully again"'
        self.assertEqual(
            strip_unverifiable_quotes(summary, TWO_TURNS),
            "The customer said it finished succesfully again",
        )

    def test_quote_from_a_single_message_is_kept(self):
        summary = 'The customer said it ran "sucessfully again"'
        self.assertEqual(strip_unverifiable_quotes(summary, TWO_TURNS), summary)

    def test_only_the_unverifiable_span_loses_its_marks(self):
        summary = 'They said "the sync is failing" and "the sync exploded"'
        self.assertEqual(
            strip_unverifiable_quotes(summary, ["the sync is failing"]),
            'They said "the sync is failing" and the sync exploded',
        )

    def test_unverifiable_quotes_reports_the_offending_spans(self):
        summary = 'They said "the sync is failing" and "the sync exploded"'
        self.assertEqual(unverifiable_quotes(summary, ["the sync is failing"]), ["the sync exploded"])

    def test_a_multi_line_quote_does_not_swallow_the_words_after_it(self):
        turns = ["Automation failed: undefined at Move ticket\nFired by Event: $conversation_message_received"]
        error = "Automation failed: undefined at Move ticket\nFired by Event: $conversation_message_received"
        self.assertEqual(
            strip_unverifiable_quotes(f'The customer pasted "{error}" and then said "it broke everything".', turns),
            f'The customer pasted "{error}" and then said it broke everything.',
        )

    def test_text_after_a_nested_quote_mark_is_still_verified(self):
        turns = ['  File "sync/runner.py", line 88, in execute']
        summary = 'Traceback: "File "sync/runner.py", line 88, in execute\\n rows = fetch()"'
        self.assertEqual(
            unverifiable_quotes(summary, turns),
            [", line 88, in execute\\n rows = fetch()"],
        )

    @parameterized.expand(
        [
            ("curly marks around the customer's words are kept", "“the sync is failing”", "“the sync is failing”"),
            ("curly marks around invented words are stripped", "“the sync exploded”", "the sync exploded"),
        ]
    )
    def test_curly_quotation_marks_are_verified_too(self, _name, quoted, expected):
        self.assertEqual(
            strip_unverifiable_quotes(f"They said {quoted} today", ["the sync is failing"]),
            f"They said {expected} today",
        )
