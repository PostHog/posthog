from collections import defaultdict
from datetime import timedelta
from typing import Dict, List, Optional, Tuple, Union

from celery.app import shared_task
from django.db import connection
from django.db.models import Count
from django.db.models.query import QuerySet
from django.utils.timezone import now

from posthog.ee import is_ee_enabled
from posthog.models import Team
from posthog.models.dashboard_item import DashboardItem
from posthog.models.event import Event

ValueByTeamEvent = Dict[Tuple[int, str], int]


def calculate_event_property_usage() -> None:
    CalculateEventPropertyUsage().run()


def key_by_team_and_event(query_results: List[Tuple[int, str, int]]) -> ValueByTeamEvent:
    return {(team_id, event): value for team_id, event, value in query_results}


class CalculateEventPropertyUsage:
    _teams: QuerySet
    _event_names_dict: Dict[int, Dict[str, Dict[str, Union[int, str]]]] = {}
    _event_properties_dict: Dict[int, Dict[str, Dict[str, Union[int, str]]]] = {}

    def __init__(self, clickhouse_volume_cutoff: int = 1_000_000) -> None:
        # Number of events at which we query events individually
        # Only set in tests
        self._clickhouse_volume_cutoff = clickhouse_volume_cutoff
        self.team_calculators = [CalculateTeamEventPropertyUsage(team) for team in Team.objects.all()]

    def run(self) -> None:
        for team_calculator in self.team_calculators:
            team_calculator.populate_event_usage_count()
            team_calculator.save()

        event_volumes = self._get_events_volume()
        for team_calculator in self.team_calculators:
            team_calculator.populate_event_volume(event_volumes)
            team_calculator.save()

        if is_ee_enabled():
            self._clickhouse_calculate_properties_volume()
        else:
            volumes = self._psql_get_properties_volume()
            for team_calculator in self.team_calculators:
                team_calculator.populate_property_volume(volumes)
                team_calculator.save()

    def _psql_get_properties_volume(self) -> ValueByTeamEvent:
        timestamp = now() - timedelta(days=30)
        cursor = connection.cursor()
        cursor.execute(
            "SELECT team_id, json_build_array(jsonb_object_keys(properties)) ->> 0 as key1, count(1) FROM posthog_event WHERE timestamp > %s group by team_id, key1 order by count desc",
            [timestamp],
        )
        return key_by_team_and_event(cursor.fetchall())

    def _clickhouse_calculate_properties_volume(self) -> None:
        from ee.clickhouse.client import sync_execute
        from ee.clickhouse.sql.events import GET_PROPERTIES_FOR_TEAM, GET_PROPERTIES_LOW_VOLUME

        timestamp = now() - timedelta(days=30)

        # Combine all low volume clients in one query
        low_usage_volumes = key_by_team_and_event(
            sync_execute(GET_PROPERTIES_LOW_VOLUME, {"timestamp": timestamp, "cutoff": self._clickhouse_volume_cutoff},)
        )
        for team_calculator in self.team_calculators:
            team_calculator.populate_property_volume(low_usage_volumes)
            team_calculator.save()

        high_volume_clients = set(
            team_id[0]
            for team_id in sync_execute(
                "SELECT team_id FROM (SELECT team_id, count(1) as count FROM events GROUP BY team_id) WHERE count >= {}".format(
                    self._clickhouse_volume_cutoff
                ),
                {"timestamp": timestamp},
            )
        )
        for team_calculator in self.team_calculators:
            if team_calculator.team.pk in high_volume_clients:
                volume = key_by_team_and_event(
                    sync_execute(GET_PROPERTIES_FOR_TEAM, {"timestamp": timestamp, "team_id": team_calculator.team.pk},)
                )
                team_calculator.populate_property_volume(volume)
                team_calculator.save()

    def _get_events_volume(self) -> ValueByTeamEvent:
        timestamp = now() - timedelta(days=30)
        if is_ee_enabled():
            from ee.clickhouse.client import sync_execute
            from ee.clickhouse.sql.events import GET_EVENTS_VOLUME

            return key_by_team_and_event(sync_execute(GET_EVENTS_VOLUME, {"timestamp": timestamp},))
        return key_by_team_and_event(
            Event.objects.filter(timestamp__gt=timestamp)
            .values("team_id", "event")
            .annotate(count=Count("id"))
            .values_list("team_id", "event", "count")
        )


class CalculateTeamEventPropertyUsage:
    def __init__(self, team: Team) -> None:
        self.team = team
        self.event_usage_count: Dict[str, int] = defaultdict(int)
        self.event_properties_count: Dict[str, int] = defaultdict(int)
        self.event_usage_volume: Dict[str, int] = defaultdict(int)
        self.event_properties_volume: Dict[str, int] = defaultdict(int)

    def populate_event_usage_count(self) -> None:
        for item in DashboardItem.objects.filter(team=self.team, created_at__gt=now() - timedelta(days=30)):
            for event in item.filters.get("events", []):
                self.event_usage_count[event["id"]] += 1

            for prop in item.filters.get("properties", []):
                if "key" in prop:  # Note: Only needed if we need none protection
                    self.event_properties_count[prop["key"]] += 1

    def populate_event_volume(self, event_usage_volume: ValueByTeamEvent) -> None:
        self._populate(self.team.event_names, event_usage_volume, self.event_usage_volume)

    def populate_property_volume(self, property_usage_volume: ValueByTeamEvent) -> None:
        self._populate(self.team.event_properties, property_usage_volume, self.event_properties_volume)

    def _populate(self, keys: List[str], usage_dict: ValueByTeamEvent, counts_object: Dict[str, int]) -> None:
        for key in keys:
            counts_object[key] = usage_dict.get((self.team.pk, key), 0)

    def save(self) -> None:
        self.team.event_names_with_usage = self._construct_usage_volume_list(
            "event", self.team.event_names, self.event_usage_count, self.event_usage_volume
        )
        self.team.event_properties_with_usage = self._construct_usage_volume_list(
            "key", self.team.event_properties, self.event_properties_count, self.event_properties_volume
        )
        self.team.save()

    def _construct_usage_volume_list(
        self, key_name: str, keys: Dict[str, int], usage_counts: Dict[str, int], volumes: Dict[str, int]
    ) -> List:
        to_sort = [{key_name: key, "usage_count": usage_counts[key], "volume": volumes[key]} for key in keys]

        return sorted(to_sort, key=lambda item: (item.get("usage_count", 0), item.get("volume", 0)), reverse=True)
