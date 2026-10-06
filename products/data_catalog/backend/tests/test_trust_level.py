from datetime import UTC, datetime

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team, User

from products.data_catalog.backend.facade.enums import APPROVED_ICON, UNAPPROVED_ICON
from products.data_catalog.backend.logic.trust_level import build_provenance
from products.data_catalog.backend.models import Metric


class TestMetricProvenance(SimpleTestCase):
    @parameterized.expand(
        [
            ("approved_in_sync", "approved", False, "approved", APPROVED_ICON),
            ("approved_but_drifted", "approved", True, "drifted", UNAPPROVED_ICON),
            ("proposed", "proposed", False, "proposed", UNAPPROVED_ICON),
            ("proposed_and_drifted", "proposed", True, "proposed", UNAPPROVED_ICON),
        ]
    )
    def test_only_an_approved_in_sync_metric_gets_the_approved_label(
        self, _name: str, metric_status: str, is_drifted: bool, expected_tier: str, expected_icon: str
    ) -> None:
        metric = Metric(name="daily_active_orgs", display_name="Daily active orgs", status=metric_status)

        provenance = build_provenance(Team(id=7), metric, is_drifted)

        assert provenance["tier"] == expected_tier
        assert provenance["label"].startswith(expected_icon)
        assert "[Daily active orgs](" in provenance["label"]
        assert "/project/7/data-catalog/metrics/daily_active_orgs)" in provenance["label"]

    @parameterized.expand(
        [
            ("named_approver", "Ada", "Lovelace", "reviewed by Ada Lovelace on Sep 2, 2026"),
            ("nameless_approver", "", "", "reviewed by your team on Sep 2, 2026"),
        ]
    )
    def test_approved_label_names_the_reviewer(self, _name: str, first: str, last: str, expected: str) -> None:
        metric = Metric(
            name="mrr",
            status="approved",
            approved_by=User(first_name=first, last_name=last),
            approved_at=datetime(2026, 9, 2, tzinfo=UTC),
        )

        assert build_provenance(Team(id=7), metric, is_drifted=False)["label"].endswith(expected)
