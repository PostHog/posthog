import hashlib
import json
from datetime import datetime, timezone
from typing import List, Optional, Tuple, cast

import structlog
from statshog.defaults.django import statsd

from ee.clickhouse.queries.session_recordings.clickhouse_session_recording import ClickhouseSessionRecording
from ee.kafka_client.client import KafkaProducer
from ee.kafka_client.topics import KAFKA_SESSION_RECORDINGS
from posthog.client import sync_execute
from posthog.queries.session_recordings.session_recording import RecordingMetadata
from posthog.settings import OBJECT_STORAGE_SESSION_RECORDING_FOLDER
from posthog.storage import object_storage

logger = structlog.get_logger(__name__)


def get_sessions_for_oldest_partition() -> List[Tuple[str, int, str]]:
    # todo don't just template variables into sql

    query_result = sync_execute(
        f"""
        with (SELECT toYYYYMMDD(min(timestamp)) FROM session_recording_events) as partition
            SELECT session_id, team_id, partition
            FROM session_recording_events
            WHERE toYYYYMMDD(timestamp) = partition
            GROUP BY session_id, team_id
        """,
    )

    return [(session_id, team_id, str(partition)) for session_id, team_id, partition in query_result]


def process_finished_session(session_id: str, team_id: int, partition: str) -> bool:
    """
    for each session
        * calculate session metadata and load/decompress the snapshot data
        * split the data by something...
           * if length is less than "some value" then it is a single bundle
           * otherwise bundle (by full chunks) about 1kb, then 2kb, then equal chunks for the remainder
        * write those to S3 (treat compressing that file as an optimisation)
        * if that succeeds write that session to metadata table

    when all of those sessions have a record in the metadata table the partition can be dropped

    """
    logger.debug("session_recordings.process_finished_session.starting")
    timer = statsd.timer("session_recordings.process_finished_session").start()

    try:
        recording = ClickhouseSessionRecording(team_id=team_id, session_recording_id=session_id)
        metadata: Optional[RecordingMetadata] = recording.get_metadata()
        # yee-haw! load all the data
        snapshot_data = recording.get_snapshots(limit=None, offset=0)

        if not metadata or not snapshot_data:
            statsd.incr("session_recordings.process_finished_sessions.skipping_empty", tags={"team_id": team_id,})
            return False

        # todo how are we asserting it is safe to call it finished!
        first_start_time = min(
            [cast(datetime, x["start_time"]) for x in metadata.start_and_end_times_by_window_id.values()]
        )
        last_end_time = max([cast(datetime, x["end_time"]) for x in metadata.start_and_end_times_by_window_id.values()])

        # must be more than 48 hours since last event to be considered finished
        if (datetime.now(timezone.utc) - last_end_time).total_seconds() // 3600 < 48:
            statsd.incr(
                "session_recordings.process_finished_sessions.skipping_recently_active", tags={"team_id": team_id,}
            )
            return False

        # YOLO write the whole thing as a single file
        object_storage_path = "/".join(
            [OBJECT_STORAGE_SESSION_RECORDING_FOLDER, str(partition), str(team_id), session_id, "1"]
        )
        object_storage.write(object_storage_path, json.dumps(snapshot_data.snapshot_data_by_window_id))

        # fling it at kafka
        partition_key = hashlib.sha256(f"{team_id}:{session_id}".encode()).hexdigest()
        kafka_payload = {
            "session_id": session_id,
            "team_id": team_id,
            "distinct_id": metadata.distinct_id,
            "session_start": first_start_time.isoformat(),
            "session_end": last_end_time.isoformat(),
            "duration": (first_start_time - last_end_time).total_seconds(),
            "segments": [segment.to_dict() for segment in metadata.segments],
            "start_and_end_times_by_window_id": {
                window_id: {time_key: time.isoformat() for (time_key, time) in time_dict.items()}
                for (window_id, time_dict) in metadata.start_and_end_times_by_window_id.items()
            },
            "snapshot_data_location": {1: object_storage_path},
        }
        KafkaProducer(test=False).produce(
            # don't allow test mode to affect topic used
            topic=KAFKA_SESSION_RECORDINGS,
            data=kafka_payload,
            key=partition_key,
        )
        statsd.incr("session_recordings.process_finished_session.succeeded", tags={"team_id": team_id,})

    except Exception as e:
        statsd.incr("session_recordings.process_finished_session.failed", tags={"team_id": team_id,})
        logger.error(
            "session_recordings.process_finished_session.failed_writing_to_kafka",
            topic=KAFKA_SESSION_RECORDINGS,
            error=e,
            session_id=session_id,
        )
        raise e

    finally:
        timer.stop()

    return True
