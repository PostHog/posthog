from typing import Callable

from freezegun import freeze_time

from posthog.models import DashboardItem, Event, Organization, Team
from posthog.tasks.calculate_event_property_usage import calculate_event_property_usage_for_team
from posthog.test.base import BaseTest


def test_calculate_event_property_usage(create_event: Callable) -> Callable:
    class Test(BaseTest):
        def test_calculate_usage(self) -> None:
            self.team.event_names = ["$pageview", "custom event"]
            self.team.event_properties = ["$current_url", "team_id", "value"]
            self.team.save()
            team2 = Organization.objects.bootstrap(None)[2]
            with freeze_time("2020-08-01"):
                # ignore stuff older than 30 days
                DashboardItem.objects.create(
                    team=self.team,
                    filters={
                        "events": [{"id": "$pageview"}],
                        "properties": [{"key": "$current_url", "value": "https://posthog.com"}],
                    },
                )
                create_event(
                    distinct_id="test",
                    team=self.team,
                    event="$pageview",
                    properties={"$current_url": "https://posthog.com"},
                )
            with freeze_time("2020-10-01"):
                DashboardItem.objects.create(
                    team=self.team,
                    filters={
                        "events": [{"id": "$pageview"}],
                        "properties": [{"key": "$current_url", "value": "https://posthog.com"}],
                    },
                )
                DashboardItem.objects.create(
                    team=self.team,
                    filters={
                        "events": [{"id": "$pageview"}],
                        "properties": [{"key": "$current_url", "value": "https://posthog2.com"}],
                    },
                )
                DashboardItem.objects.create(
                    team=self.team,
                    filters={"events": [{"id": "custom event"}], "properties": [{"key": "team_id", "value": "3"}]},
                )
                DashboardItem.objects.create(team=self.team, filters={"events": [{"id": "event that doesnt exist"}]})
                # broken dashboard item
                DashboardItem.objects.create(team=self.team, filters={})
                create_event(
                    distinct_id="test",
                    team=self.team,
                    event="$pageview",
                    properties={"$current_url": "https://posthog.com"},
                )
                create_event(
                    distinct_id="test",
                    team=self.team,
                    event="$pageview",
                    properties={"$current_url": "https://posthog2.com"},
                )
                create_event(distinct_id="test", team=self.team, event="custom event", properties={"team_id": "3"})

                # team leakage
                create_event(
                    distinct_id="test",
                    team=team2,
                    event="$pageview",
                    properties={"$current_url": "https://posthog.com"},
                )
                DashboardItem.objects.create(
                    team=team2,
                    filters={
                        "events": [{"id": "$pageview"}],
                        "properties": [{"key": "$current_url", "value": "https://posthog.com"}],
                    },
                )

                calculate_event_property_usage_for_team(self.team.pk)
            team = Team.objects.get(pk=self.team.pk)
            self.assertEqual(
                team.event_names_with_usage,
                [
                    {"event": "$pageview", "usage_count": 2, "volume": 2},
                    {"event": "custom event", "usage_count": 1, "volume": 1},
                ],
            )
            self.assertEqual(
                team.event_properties_with_usage,
                [
                    {"key": "$current_url", "usage_count": 2, "volume": 2},
                    {"key": "team_id", "usage_count": 1, "volume": 1},
                    {"key": "value", "usage_count": 0, "volume": 0},
                ],
            )

    return Test


class Test(test_calculate_event_property_usage(Event.objects.create)):  # type: ignore
    pass
