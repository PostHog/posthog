from datetime import datetime, timedelta

from posthog.session_recordings.session_recording_v2_service import RecordingBlock
from posthog.temporal.delete_recordings.activities import group_recording_blocks
from posthog.temporal.delete_recordings.types import Recording, RecordingBlockGroup, RecordingWithBlocks


async def test_single_group_recording_blocks():
    test_input = RecordingWithBlocks(
        recording=Recording(
            session_id="abc",
            team_id=123,
        ),
        blocks=[
            RecordingBlock(
                start_time=datetime.now() - timedelta(minutes=5),
                end_time=datetime.now() - timedelta(minutes=3),
                url="s3://test_bucket/session_recordings/5y/1756117699905-b688321ffa0fa994?range=bytes=12269307-12294780",
            ),
            RecordingBlock(
                start_time=datetime.now() - timedelta(minutes=15),
                end_time=datetime.now() - timedelta(minutes=13),
                url="s3://test_bucket/session_recordings/5y/1756117699905-b688321ffa0fa994?range=bytes=81788204-81793010",
            ),
        ],
    )

    expected_output = [
        RecordingBlockGroup(
            recording=Recording(
                session_id="abc",
                team_id=123,
            ),
            path="session_recordings/5y/1756117699905-b688321ffa0fa994",
            ranges=[
                (12269307, 12294780),
                (81788204, 81793010),
            ],
        )
    ]

    assert await group_recording_blocks(test_input) == expected_output


async def test_multiple_group_recording_blocks():
    test_input = RecordingWithBlocks(
        recording=Recording(
            session_id="abc",
            team_id=123,
        ),
        blocks=[
            RecordingBlock(
                start_time=datetime.now() - timedelta(minutes=5),
                end_time=datetime.now() - timedelta(minutes=3),
                url="s3://test_bucket/session_recordings/5y/1756117699905-b688321ffa0fa994?range=bytes=12269307-12294780",
            ),
            RecordingBlock(
                start_time=datetime.now() - timedelta(minutes=15),
                end_time=datetime.now() - timedelta(minutes=13),
                url="s3://test_bucket/session_recordings/5y/1756117699905-b688321ffa0fa994?range=bytes=81788204-81793010",
            ),
            RecordingBlock(
                start_time=datetime.now() - timedelta(minutes=15),
                end_time=datetime.now() - timedelta(minutes=13),
                url="s3://test_bucket/session_recordings/90d/1756117747546-97a0b1e81d492d3a?range=bytes=2790658-2800843",
            ),
            RecordingBlock(
                start_time=datetime.now() - timedelta(minutes=15),
                end_time=datetime.now() - timedelta(minutes=13),
                url="s3://test_bucket/session_recordings/1y/1756117652764-84b1bccb847e7ea6?range=bytes=12269307-12294780",
            ),
            RecordingBlock(
                start_time=datetime.now() - timedelta(minutes=15),
                end_time=datetime.now() - timedelta(minutes=13),
                url="s3://test_bucket/session_recordings/5y/1756117699905-b688321ffa0fa994?range=bytes=2790658-2800843",
            ),
        ],
    )

    expected_output = [
        RecordingBlockGroup(
            recording=Recording(
                session_id="abc",
                team_id=123,
            ),
            path="session_recordings/5y/1756117699905-b688321ffa0fa994",
            ranges=[
                (12269307, 12294780),
                (81788204, 81793010),
                (2790658, 2800843),
            ],
        ),
        RecordingBlockGroup(
            recording=Recording(
                session_id="abc",
                team_id=123,
            ),
            path="session_recordings/90d/1756117747546-97a0b1e81d492d3a",
            ranges=[
                (2790658, 2800843),
            ],
        ),
        RecordingBlockGroup(
            recording=Recording(
                session_id="abc",
                team_id=123,
            ),
            path="session_recordings/1y/1756117652764-84b1bccb847e7ea6",
            ranges=[
                (12269307, 12294780),
            ],
        ),
    ]

    assert await group_recording_blocks(test_input) == expected_output
