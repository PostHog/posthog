import dataclasses
import json
import math
from datetime import datetime
from typing import Dict, List, Optional

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.client import sync_execute


@dataclasses.dataclass
class PlayerPosition:
    time: int
    windowId: str

    @property
    def __dict__(self):
        return dataclasses.asdict(self)


@dataclasses.dataclass
class WebPerformanceLog:
    playerPosition: PlayerPosition
    type: str
    url: Optional[str]
    eventName: Optional[str]
    duration: Optional[int]
    timing: Optional[int]
    eventId: Optional[int]
    raw: Dict

    @property
    def __dict__(self):
        return dataclasses.asdict(self)


class WebPerformanceViewSet(StructuredViewSetMixin, viewsets.GenericViewSet):
    @action(methods=["GET"], detail=False, url_path="for_session/(?P<session_id>[^/.]+)")
    def for_session(self, request, session_id, *args, **kwargs) -> Response:
        # todo materialised column method instead of hard coded json extract raw?
        query = """
        SELECT timestamp, JSONExtractRaw(properties, '$performance_raw'), $window_id, uuid
        FROM events
        WHERE event = '$pageview'
        and team_id = %(team_id)s
        AND $session_id = %(session_id)s
        """
        query_result = sync_execute(query, {"team_id": self.team.id, "session_id": session_id,},)

        parsed_entries: List[WebPerformanceLog] = []
        keys: Dict[str, List[str]] = {}
        for res in query_result:
            # whaaat a tuple whose first entry is doubly stringified JSON
            pageview_timestamp = res[0]
            start_timestamp = math.floor(datetime.timestamp(pageview_timestamp) * 1000)
            performance_entries: Dict = json.loads(json.loads(res[1]))
            window_id = res[2]

            # each is an array of arrays, the first entry is an array of the property names,
            # the remaining are each an array of the values for each of the properties in the first index
            # really lazy hard coding indexes :/
            keys["navigation"] = performance_entries.get("navigation", [])[0]
            for navigation_entry in performance_entries.get("navigation", [])[1]:
                # 0: name e.g. the URL,
                # 1: entryType (always navigation),
                # 2: duration,
                # startTime not present because its always 0
                parsed_entries.append(
                    WebPerformanceLog(
                        playerPosition=PlayerPosition(time=start_timestamp, windowId=window_id),
                        type="navigation",
                        duration=navigation_entry[2],
                        timing=None,
                        eventName=None,
                        url=navigation_entry[0],
                        raw=navigation_entry,
                        eventId=res[3],
                    )
                )

            keys["paint"] = performance_entries.get("paint", [])[0]
            for paint_entry in performance_entries.get("paint", [])[1]:
                # 0: name, 2: milliseconds of event after start
                parsed_entries.append(
                    WebPerformanceLog(
                        playerPosition=PlayerPosition(time=start_timestamp + paint_entry[2], windowId=window_id),
                        type="paint",
                        duration=None,
                        url=None,
                        eventName=paint_entry[0],
                        eventId=None,
                        timing=paint_entry[2],
                        raw=paint_entry,
                    )
                )

            keys["resource"] = performance_entries.get("resource", [])[0]
            for resource_entry in performance_entries.get("resource", [])[1]:
                # 0 name, 1: startTime, 2: duration
                parsed_entries.append(
                    WebPerformanceLog(
                        playerPosition=PlayerPosition(time=start_timestamp + resource_entry[1], windowId=window_id),
                        type="resource",
                        duration=resource_entry[2],
                        url=resource_entry[0],
                        timing=None,
                        eventName=None,
                        eventId=None,
                        raw=resource_entry,
                    )
                )

        # todo a real serializer
        return Response(
            {
                "keys": keys,
                "results": [e.__dict__ for e in sorted(parsed_entries, key=lambda x: x.playerPosition.time)],
            }
        )
