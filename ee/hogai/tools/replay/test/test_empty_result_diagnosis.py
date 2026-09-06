from django.test import SimpleTestCase

from parameterized import parameterized

from ee.hogai.tools.replay.empty_result_diagnosis import EmptyResultCause, EventSessionLinkage, describe, diagnose


class TestEmptyResultDiagnosis(SimpleTestCase):
    @parameterized.expand(
        [
            ("no filtered events", (), EmptyResultCause.NO_EVENTS),
            (
                "event never sent",
                ((0, 0),),
                EmptyResultCause.NO_EVENTS,
            ),
            (
                "every event sent without a session id",
                ((500, 0),),
                EmptyResultCause.EVENTS_NOT_LINKED,
            ),
            (
                "session ids on a negligible share of events",
                ((1000, 20),),
                EmptyResultCause.EVENTS_NOT_LINKED,
            ),
            (
                "one linked event and one unlinked event",
                ((100, 100), (100, 0)),
                EmptyResultCause.EVENTS_NOT_LINKED,
            ),
            (
                "every event fully linked",
                ((100, 100),),
                EmptyResultCause.FILTERS_TOO_NARROW,
            ),
            (
                "coverage just above the unlinked threshold",
                ((100, 11),),
                EmptyResultCause.FILTERS_TOO_NARROW,
            ),
        ]
    )
    def test_cause_for_linkage(
        self, _name: str, counts: tuple[tuple[int, int], ...], expected: EmptyResultCause
    ) -> None:
        linkages = tuple(
            EventSessionLinkage(event=f"event_{i}", total=total, linked=linked)
            for i, (total, linked) in enumerate(counts)
        )

        self.assertEqual(diagnose(linkages).cause, expected)

    def test_unlinked_guidance_offers_a_scanner_and_names_the_event(self) -> None:
        linkages = (EventSessionLinkage(event="paywall_shown", total=800, linked=0),)

        guidance = describe(diagnose(linkages))

        self.assertIn("paywall_shown", guidance)
        self.assertIn("800 events", guidance)
        self.assertIn("Replay Vision scanner", guidance)

    @parameterized.expand(
        [
            ("event never sent", (EventSessionLinkage(event="paywall_shown", total=0, linked=0),)),
            ("events fully linked", (EventSessionLinkage(event="paywall_shown", total=100, linked=100),)),
        ]
    )
    def test_scanner_is_not_offered_when_linkage_is_not_the_problem(
        self, _name: str, linkages: tuple[EventSessionLinkage, ...]
    ) -> None:
        guidance = describe(diagnose(linkages))

        self.assertIn("Do not offer a Replay Vision scanner", guidance)
