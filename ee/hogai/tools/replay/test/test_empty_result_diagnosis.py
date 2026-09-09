from django.test import SimpleTestCase

from parameterized import parameterized

from ee.hogai.tools.replay.empty_result_diagnosis import (
    SESSION_ID_DOCS_URL,
    EmptyResultCause,
    EventSessionLinkage,
    describe,
    diagnose,
)


def _linkages(*counts: tuple[int, int]) -> tuple[EventSessionLinkage, ...]:
    return tuple(
        EventSessionLinkage(event=f"event_{i}", total=total, linked=linked) for i, (total, linked) in enumerate(counts)
    )


class TestEmptyResultDiagnosis(SimpleTestCase):
    @parameterized.expand(
        [
            ("event never sent", ((0, 0),), False, True, EmptyResultCause.NO_EVENTS, ["event_0"]),
            ("every event unlinked", ((500, 0),), False, True, EmptyResultCause.EVENTS_NOT_LINKED, ["event_0"]),
            ("coverage at threshold", ((100, 11),), False, True, EmptyResultCause.FILTERS_TOO_NARROW, ["event_0"]),
            ("missing and unlinked, all", ((0, 0), (100, 0)), False, True, EmptyResultCause.NO_EVENTS, ["event_0"]),
            (
                "missing and unlinked, any",
                ((0, 0), (100, 0)),
                True,
                True,
                EmptyResultCause.EVENTS_NOT_LINKED,
                ["event_1"],
            ),
            (
                "linked and unlinked, all",
                ((100, 100), (100, 0)),
                False,
                True,
                EmptyResultCause.EVENTS_NOT_LINKED,
                ["event_1"],
            ),
            (
                "linked and unlinked, any",
                ((100, 100), (100, 0)),
                True,
                True,
                EmptyResultCause.FILTERS_TOO_NARROW,
                ["event_0", "event_1"],
            ),
            (
                "linked, recording disabled",
                ((100, 100),),
                False,
                False,
                EmptyResultCause.RECORDING_DISABLED,
                ["event_0"],
            ),
        ]
    )
    def test_cause_for_linkage(
        self,
        _name: str,
        counts: tuple[tuple[int, int], ...],
        match_any: bool,
        recording_enabled: bool,
        expected: EmptyResultCause,
        expected_events: list[str],
    ) -> None:
        diagnosis = diagnose(_linkages(*counts), match_any=match_any, recording_enabled=recording_enabled)

        self.assertEqual(diagnosis.cause, expected)
        self.assertEqual([linkage.event for linkage in diagnosis.linkages], expected_events)

    def test_unlinked_guidance_offers_a_scanner_and_links_docs(self) -> None:
        linkages = (EventSessionLinkage(event="paywall_shown", total=800, linked=0),)

        guidance = describe(diagnose(linkages, match_any=False, recording_enabled=True))

        self.assertIn("paywall_shown", guidance)
        self.assertIn("800 events", guidance)
        self.assertIn("Replay Vision scanner", guidance)
        self.assertIn(SESSION_ID_DOCS_URL, guidance)

    @parameterized.expand(
        [
            ("event never sent", (0, 0), True),
            ("events fully linked", (100, 100), True),
            ("recording disabled", (100, 100), False),
        ]
    )
    def test_scanner_is_not_offered_when_linkage_is_not_the_problem(
        self, _name: str, counts: tuple[int, int], recording_enabled: bool
    ) -> None:
        guidance = describe(diagnose(_linkages(counts), match_any=False, recording_enabled=recording_enabled))

        self.assertIn("Do not offer a Replay Vision scanner", guidance)
