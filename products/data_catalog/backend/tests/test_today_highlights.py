from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.data_catalog.backend import today_highlights
from products.data_catalog.backend.facade.api import PendingGroup, PendingKind, TeamPendingReview
from products.data_catalog.backend.facade.today_highlights import HIGHLIGHT_SOURCES
from products.today.backend.facade.contracts import HighlightContext, HighlightFindings
from products.today.backend.facade.enums import HighlightLabel

METRICS = PendingGroup(kind=PendingKind.METRICS, noun="metric", count=3, sample_names=[])
RELATIONSHIPS = PendingGroup(kind=PendingKind.RELATIONSHIPS, noun="relationship", count=2, sample_names=[])
ONE_CERTIFICATION = PendingGroup(kind=PendingKind.CERTIFICATIONS, noun="certification", count=1, sample_names=[])


class TestDataCatalogApprovalsHighlight(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "one item uses the singular",
                [ONE_CERTIFICATION],
                "1 certification waits for approval",
                "Review it in the data catalog.",
                "/data-catalog?tab=certifications",
            ),
            (
                "several queues join their counts and link the first queue",
                [METRICS, RELATIONSHIPS, ONE_CERTIFICATION],
                "3 metrics, 2 relationships and 1 certification wait for approval",
                "Review them in the data catalog.",
                "/data-catalog?tab=metrics",
            ),
        ]
    )
    def test_pending_queues_are_one_opportunity_item(
        self, _name: str, groups: list[PendingGroup], title: str, detail: str, url: str
    ) -> None:
        review = TeamPendingReview(
            team_id=1, team_name="Team", groups=groups, total=sum(group.count for group in groups)
        )
        registered = next(source for source in HIGHLIGHT_SOURCES if source.name == "data_catalog_approvals")

        with patch.object(today_highlights, "build_team_pending_review", return_value=review):
            found = self._find(registered.find, can_approve=True)

        assert len(found.items) == 1
        item = found.items[0]
        assert (item.title, item.detail, item.url) == (title, detail, url)
        assert item.label == HighlightLabel.OPPORTUNITY
        assert (item.importance, item.relevance) == (0.5, 1.0)
        assert registered.scopes == ("data_catalog:read", "data_catalog_approval:write")

    def test_a_user_who_cannot_approve_gets_no_item(self) -> None:
        review = TeamPendingReview(team_id=1, team_name="Team", groups=[METRICS], total=3)

        with patch.object(today_highlights, "build_team_pending_review", return_value=review):
            found = self._find(today_highlights.find_pending_approvals, can_approve=False)

        assert found.items == ()

    def _find(self, find: Callable[[HighlightContext], HighlightFindings], *, can_approve: bool) -> HighlightFindings:
        access = MagicMock()
        access.check_access_level_for_resource.side_effect = lambda resource, level: (
            can_approve and (resource, level) == ("data_catalog", "editor")
        )
        context = cast(HighlightContext, SimpleNamespace(team=SimpleNamespace(id=1), user=SimpleNamespace(id=2)))
        with patch.object(today_highlights, "UserAccessControl", return_value=access):
            return find(context)
