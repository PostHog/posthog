from datetime import UTC, datetime

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team, User

from products.data_catalog.backend.facade.enums import APPROVED_ICON
from products.data_catalog.backend.logic.trust_badge import build_trust_badge
from products.data_catalog.backend.models import Metric


class TestMetricTrustBadge(SimpleTestCase):
    @parameterized.expand(
        [
            ("approved_but_drifted", "approved", True),
            ("proposed", "proposed", False),
            ("proposed_and_drifted", "proposed", True),
        ]
    )
    def test_no_badge_unless_approved_and_in_sync(self, _name: str, metric_status: str, is_drifted: bool) -> None:
        metric = Metric(name="daily_active_orgs", status=metric_status)

        assert build_trust_badge(Team(id=7), metric, is_drifted) is None

    @parameterized.expand(
        [
            ("named_approver", "Ada", "Lovelace", "reviewed by Ada Lovelace on Sep 2, 2026"),
            ("nameless_approver", "", "", "reviewed by your team on Sep 2, 2026"),
        ]
    )
    def test_approved_badge_links_the_metric_and_names_the_reviewer(
        self, _name: str, first: str, last: str, expected_reviewer: str
    ) -> None:
        metric = Metric(
            name="daily_active_orgs",
            display_name="Daily active orgs",
            status="approved",
            approved_by=User(first_name=first, last_name=last),
            approved_at=datetime(2026, 9, 2, tzinfo=UTC),
        )

        badge = build_trust_badge(Team(id=7), metric, is_drifted=False)

        assert badge is not None
        assert badge.startswith(APPROVED_ICON)
        assert "[Daily active orgs](" in badge
        assert "/project/7/data-catalog/metrics/daily_active_orgs)" in badge
        assert badge.endswith(expected_reviewer)
