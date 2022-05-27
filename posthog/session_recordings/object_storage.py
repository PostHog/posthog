import json
from typing import Dict, Optional

import structlog
from django.conf import settings
from statshog.defaults.django import statsd

from posthog.storage import object_storage

logger = structlog.get_logger(__name__)


def read_snapshot_data(snapshot_data: str, team_id: int) -> Dict:
    """
    Session recording payloads were originally stored in ClickHouse, using a lot of expensive storage
    Now, the plugin server (when configured to) stores the data in object storage
    and may in future remove the snapshot data from the ClickHouse event

    The data must be present in either the ClickHouse entry or object storage to be valid
    """

    json_data = json.loads(snapshot_data)

    if not settings.OBJECT_STORAGE_ENABLED:
        return json_data

    object_storage_path: Optional[str] = None
    timer = statsd.timer("session_recording.object_storage.read", tags={"team_id": team_id}).start()
    try:
        object_storage_path = json_data.get("object_storage_path", None)
        if object_storage_path:
            file_content = object_storage.read(object_storage_path)
            statsd.incr("session_recording.object_storage.read.success", tags={"team_id": team_id})

            json_data["data"] = file_content
    except Exception as e:
        logger.error("session_recording.object_storage.read.error", team_id=team_id, error=e, path=object_storage_path)
        statsd.incr("session_recording.object_storage.read.error", tags={"team_id": team_id})

    timer.stop()
    return json_data
