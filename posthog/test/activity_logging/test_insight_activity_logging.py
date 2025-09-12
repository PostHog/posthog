import random
import string

from posthog.test.base import BaseTest

from dateutil import parser

from posthog.models import Dashboard, DashboardTile, Insight, Tag
from posthog.models.activity_logging.activity_log import Change, changes_between


class TestChangesBetweenInsights(BaseTest):
    def test_a_change_of_insight_dashboard_can_be_logged(self) -> None:
        insight_before = self._an_insight_with(name="name", tagged_items=[])
        insight_after = self._an_insight_with(name="name", tagged_items=[])
        dashboard = Dashboard.objects.create(team=self.team, name="the dashboard")
        DashboardTile.objects.create(insight=insight_after, dashboard=dashboard)

        actual = changes_between(model_type="Insight", previous=insight_before, current=insight_after)
        expected = [
            Change(
                type="Insight",
                action="changed",
                field="dashboards",
                before=[],
                after=[
                    {
                        "dashboard": {"id": dashboard.id, "name": dashboard.name},
                        "insight": {"id": insight_after.id},
                    }
                ],
            ),
        ]

        assert actual == expected

    def test_insight_change_of_name_can_be_logged(self) -> None:
        actual = changes_between(
            model_type="Insight",
            previous=self._an_insight_with(name="name"),
            current=self._an_insight_with(name="new name"),
        )
        expected = [
            Change(
                type="Insight",
                field="name",
                action="changed",
                before="name",
                after="new name",
            ),
        ]

        self.assertCountEqual(actual, expected)

    def test_insight_change_of_tags_can_be_logged(self) -> None:
        actual = changes_between(
            model_type="Insight",
            previous=self._an_insight_with(tagged_items=["before", "tags"]),
            current=self._an_insight_with(tagged_items=["after", "tags"]),
        )
        expected = [
            Change(
                type="Insight",
                field="tags",
                action="changed",
                before=["before", "tags"],
                after=["after", "tags"],
            ),
        ]

        self.assertCountEqual(actual, expected)

    def test_insight_change_of_derived_name_can_be_logged(self) -> None:
        actual = changes_between(
            model_type="Insight",
            previous=self._an_insight_with(derived_name="starting"),
            current=self._an_insight_with(derived_name="after"),
        )
        expected = [
            Change(
                type="Insight",
                field="derived_name",
                action="changed",
                before="starting",
                after="after",
            ),
        ]

        self.assertCountEqual(actual, expected)

    def test_insight_change_of_description_can_be_logged(self) -> None:
        actual = changes_between(
            model_type="Insight",
            previous=self._an_insight_with(description="starting"),
            current=self._an_insight_with(description="after"),
        )
        expected = [
            Change(
                type="Insight",
                field="description",
                action="changed",
                before="starting",
                after="after",
            ),
        ]

        self.assertCountEqual(actual, expected)

    def _an_insight_with(self, tagged_items=None, **kwargs) -> Insight:
        if tagged_items is None:
            tagged_items = []

        insight = Insight.objects.create(
            created_at=kwargs.get("created_at", parser.parse("12th April 2003")),
            team=kwargs.get("team", self.team),
            name=kwargs.get("name", "the name"),
            derived_name=kwargs.get("derived_name", "the derived name"),
            description=kwargs.get("description", "an insight description"),
            filters=kwargs.get("filters", {}),
            filters_hash=kwargs.get("filters_hash", "a hash string"),
            order=kwargs.get("order", 0),
            deleted=kwargs.get("deleted", False),
            saved=kwargs.get("saved", True),
            last_refresh=kwargs.get("last_refresh", parser.parse("12th April 2003")),
            refreshing=kwargs.get("refreshing", False),
            created_by=kwargs.get("user", self.user),
            is_sample=kwargs.get("is_sample", False),
            short_id=kwargs.get(
                "short_id",
                "".join(random.choices(string.ascii_letters + string.digits, k=6)),
            ),
            favorited=kwargs.get("favorited", False),
            refresh_attempt=kwargs.get("refresh_attempt", 0),
            last_modified_at=kwargs.get("last_modified_at", parser.parse("12th April 2003")),
            last_modified_by=kwargs.get("last_modified_by", self.user),
        )

        if tagged_items:
            for provided_tag in tagged_items:
                tag, _ = Tag.objects.get_or_create(name=provided_tag, team_id=self.team.id)
                insight.tagged_items.get_or_create(tag=tag)

        return insight
