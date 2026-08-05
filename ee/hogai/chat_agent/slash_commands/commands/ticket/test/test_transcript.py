from unittest import TestCase

from parameterized import parameterized

from posthog.schema import AssistantMessage, HumanMessage

from ee.hogai.chat_agent.slash_commands.commands.ticket.transcript import (
    customer_turns,
    render_transcript,
    strip_unverifiable_quotes,
    unverifiable_quotes,
)

TWO_TURNS = ["I accidently merged a PR that was reversed", "I accidenty connected it to my issue tracker"]


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
            ("nested double quote written as single is kept", "They said \"on the 'Overview' tab\" today", True),
            ("changed wording is stripped", 'They said "the sync is broken" today', False),
            ("short span is left alone", 'They said "sync" today', True),
        ]
    )
    def test_cosmetic_drift_survives_but_wording_changes_do_not(self, _name, summary, should_keep):
        turns = ['the sync is failing on the "Overview" tab']
        result = strip_unverifiable_quotes(summary, turns)
        self.assertEqual('"' in result, should_keep)

    def test_quote_assembled_from_two_messages_is_stripped(self):
        summary = 'The customer "accidently connected" their issue tracker'
        self.assertEqual(
            strip_unverifiable_quotes(summary, TWO_TURNS),
            "The customer accidently connected their issue tracker",
        )

    def test_quote_from_a_single_message_is_kept(self):
        summary = 'The customer "accidenty connected" their issue tracker'
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
