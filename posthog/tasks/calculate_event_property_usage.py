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


def calculate_event_property_usage() -> None:
    CalculateEventPropertyUsage().run()


class CalculateEventPropertyUsage:
    _teams: QuerySet
    _event_names_dict: Dict[int, Dict[str, Dict[str, Union[int, str]]]] = {}
    _event_properties_dict: Dict[int, Dict[str, Dict[str, Union[int, str]]]] = {}

    def __init__(self, clickhouse_volume_cutoff: int = 1_000_000) -> None:
        # Number of events at which we query events individually
        # Only set in tests
        self._clickhouse_volume_cutoff = clickhouse_volume_cutoff

    def run(self) -> None:
        self._teams = Team.objects.all()
        for team in self._teams:
            self.calculate_usage_count_for_team(team=team)

        self.calculate_event_volume()

        if is_ee_enabled():
            self._clickhouse_calculate_properties_volume()
        else:
            volume = self._psql_get_properties_volume()
            self.save_properties_volume(volume)

    def _save_team(self, team: Team) -> None:
        def _sort(to_sort: List) -> List:
            return sorted(to_sort, key=lambda item: (item.get("usage_count", 0), item.get("volume", 0)), reverse=True)

        team.event_names_with_usage = _sort([val for _, val in self._event_names_dict[team.pk].items()])
        team.event_properties_with_usage = _sort([val for _, val in self._event_properties_dict[team.pk].items()])
        team.save()

    def calculate_usage_count_for_team(self, team: Team) -> None:
        self._event_names_dict[team.pk] = {event: {"event": event, "usage_count": 0} for event in team.event_names}

        self._event_properties_dict[team.pk] = {key: {"key": key, "usage_count": 0} for key in team.event_properties}

        for item in DashboardItem.objects.filter(team=team, created_at__gt=now() - timedelta(days=30)):
            for event in item.filters.get("events", []):
                if event["id"] in self._event_names_dict[team.pk]:
                    self._event_names_dict[team.pk][event["id"]]["usage_count"] += 1  # type: ignore

            for prop in item.filters.get("properties", []):
                if prop.get("key") in self._event_properties_dict[team.pk]:
                    self._event_properties_dict[team.pk][prop["key"]]["usage_count"] += 1  # type: ignore

        # intermittent save in case the heavier queries don't finish
        self._save_team(team)

    def calculate_event_volume(self) -> None:
        #  Returns a list of tuples, [(team_id, event, volume)]
        events_volume = self._get_events_volume()
        for team in self._teams:
            for key in team.event_names:
                try:
                    volume = [e for e in events_volume if e[0] == team.pk and e[1] == key][0][2]
                except IndexError:
                    volume = 0
                try:
                    self._event_names_dict[team.pk][key]["volume"] = volume
                except KeyError:
                    pass

            self._save_team(team)

    def save_properties_volume(self, volume: List[Tuple[int, str, int]]) -> None:
        for team in self._teams:
            for key in team.event_properties:
                try:
                    set_volume = [e for e in volume if e[0] == team.pk and e[1] == key][0][2]
                except IndexError:
                    set_volume = 0
                try:
                    self._event_properties_dict[team.pk][key]["volume"] = set_volume
                except KeyError:
                    pass

            self._save_team(team)

    #  Returns a list of tuples, [(team_id, key, volume)]
    def _psql_get_properties_volume(self) -> List[Tuple[int, str, int]]:
        timestamp = now() - timedelta(days=30)
        cursor = connection.cursor()
        cursor.execute(
            "SELECT team_id, json_build_array(jsonb_object_keys(properties)) ->> 0 as key1, count(1) FROM posthog_event WHERE timestamp > %s group by team_id, key1 order by count desc",
            [timestamp],
        )
        return cursor.fetchall()

    def _clickhouse_calculate_properties_volume(self) -> None:
        from ee.clickhouse.client import sync_execute
        from ee.clickhouse.sql.events import GET_PROPERTIES_FOR_TEAM, GET_PROPERTIES_LOW_VOLUME

        timestamp = now() - timedelta(days=30)

        # Combine all low volume clients in one query
        volume = sync_execute(
            GET_PROPERTIES_LOW_VOLUME, {"timestamp": timestamp, "cutoff": self._clickhouse_volume_cutoff},
        )
        self.save_properties_volume(volume)

        high_volume_clients = [
            team[0]
            for team in sync_execute(
                "SELECT team_id FROM (SELECT team_id, count(1) as count FROM events GROUP BY team_id) WHERE count >= {}".format(
                    self._clickhouse_volume_cutoff
                ),
                {"timestamp": timestamp},
            )
        ]
        for team in [team for team in self._teams if team.pk in high_volume_clients]:
            volume = sync_execute(GET_PROPERTIES_FOR_TEAM, {"timestamp": timestamp, "team_id": team.pk},)
            for key in team.event_properties:
                try:
                    self._event_properties_dict[team.pk][key]["volume"] = [v[2] for v in volume if v[1] == key][0]
                except (KeyError, IndexError):
                    pass

            self._save_team(team)

    def _get_events_volume(self) -> List[Tuple[int, str, int]]:
        timestamp = now() - timedelta(days=30)
        if is_ee_enabled():
            from ee.clickhouse.client import sync_execute
            from ee.clickhouse.sql.events import GET_EVENTS_VOLUME

            return sync_execute(GET_EVENTS_VOLUME, {"timestamp": timestamp},)
        return (
            Event.objects.filter(timestamp__gt=timestamp)
            .values("team_id", "event")
            .annotate(count=Count("id"))
            .values_list("team_id", "event", "count")
        )
