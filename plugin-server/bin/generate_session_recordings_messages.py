#!/usr/bin/env python3

# This management command is intended to be used to generate Kafka messages that
# simulate those that are produced by the PostHog app when recording session
# data. The contents of the snapshot data is however not a valid rrweb snapshot
# as this isn't required for benchmarking the recordings ingestion consumer, but
# only simulates the size distribution.
#
# A single recording is one that is associated with a single "session id". A
# recording comprises a sequence of "snapshots" sent from the browser via the
# rrweb library. Each event is also associated with a "window id" as a recording
# can include multiple browser windows. The session id is regenerated every 6
# hours on the browser to impose a maximum recording length of 6 hours.
#
# At the top level of a snamshot message we have the standard keys that are sent
# from the capture endpoints to Kafka, including distinct_id, team_id,
# timestamp, and event which is always $snapshot.
#
# The $snapshot events represent both the "full snapshot" and "incremental
# snapshot" that rrweb sends. The full snapshot is sent when the page is loaded,
# and includes the entire DOM tree, and based 64 encoded embedded assets such as
# images. The incremental snapshot is sent when the page is mutated, and only
# includes the changes to the DOM tree. The incremental snapshot is sent as a
# diff from the previous snapshot.
#
# For our production data, per session_id we have on average 2 full snapshots
# with a standard deviation of 4 and an average of 40 incremental snapshots with
# a standard deviation of 214. The average size of a full snapshot is 185KB with
# a standard deviation of 160k bytes, and the average size of an incremental
# snapshot is 14KB with a standard deviation of 50k bytes.
#
# Note that we do not actually produce to Kafka, but instead print the messages,
# one JSON encoded message per line, to stdout. This is so that we can pipe the
# output to the Kafka command line tools, such as kafkacat or
# kafka-console-producer to produce the messages to Kafka, or to a file for use
# with e.g. vegeta to hit the capture endpoint (TODO: add support for this, at
# the moment we are handling the chunking of the message ourselves which means
# it won't be compatible with the capture endpoint.)
#
# For example, you could run:
#
#   ```
#   ./bin/generate_session_recordings_messages.py --count 1 | docker compose -f docker-compose.dev.yml exec -T kafka kafka-console-producer.sh --topic session_recording_events --broker-list localhost:9092
#   ```
#
# which will produce messages to the session_recording_events topic in Kafka.
#
# IMORTANT: I am assuming a log-normal distribution for counts and size. That is
# an assumption that is not backed up by any data.


import json
import uuid
import argparse
from sys import stderr, stdout

import numpy
from faker import Faker

help = "Generate Kafka messages that simulate session recording data"


def get_parser():
    parser = argparse.ArgumentParser(description=help)
    parser.add_argument(
        "--count",
        type=int,
        default=100,
        help="The number of session recordings to generate",
    )
    parser.add_argument(
        "--full-snapshot-size-mean",
        type=int,
        default=185000,
        help="The average size of a full snapshot in bytes",
    )
    parser.add_argument(
        "--full-snapshot-size-standard-deviation",
        type=int,
        default=160000,
        help="The standard deviation of the size of a full snapshot in bytes squared",
    )
    parser.add_argument(
        "--full-snapshot-count-mean",
        type=int,
        default=2,
        help="The average number of full snapshots per session",
    )
    parser.add_argument(
        "--full-snapshot-count-standard-deviation",
        type=int,
        default=4,
        help="The standard deviation of the number of full snapshots per session",
    )
    parser.add_argument(
        "--incremental-snapshot-size-mean",
        type=int,
        default=14000,
        help="The average size of an incremental snapshot in bytes",
    )
    parser.add_argument(
        "--incremental-snapshot-size-standard-deviation",
        type=int,
        default=50000,
        help="The standard deviation of the size of an incremental snapshot in bytes squared",
    )
    parser.add_argument(
        "--incremental-snapshot-count-mean",
        type=int,
        default=40,
        help="The average number of incremental snapshots per session",
    )
    parser.add_argument(
        "--incremental-snapshot-count-standard-deviation",
        type=int,
        default=214,
        help="The standard deviation of the number of incremental snapshots per session",
    )
    parser.add_argument(
        "--seed-value",
        type=int,
        default=0,
        help="The seed value to use for the random number generator",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print verbose output",
    )
    parser.add_argument(
        "--team-id",
        type=int,
        help="The team id to use for the messages.",
    )
    parser.add_argument(
        "--token",
        type=str,
        help="The token to use for the messages.",
    )
    return parser


def chunked(
    data: str,
    chunk_size: int,
) -> list[str]:
    return [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]


def sample_log_normal_distribution(
    mu: int,
    sigma: int,
    count: int,
):
    """
    Samples from a log-normal distribution with the given mean and standard
    deviation of that log distribution.
    """
    normal_std = numpy.sqrt(numpy.log(1 + (sigma / mu) ** 2))
    normal_mean = numpy.log(mu) - normal_std**2 / 2
    return [int(sample) for sample in numpy.random.lognormal(normal_mean, normal_std, count)]


def generate_snapshot_messages(
    faker: Faker,
    count: int,
    full_snapshot_size_mean: int,
    full_snapshot_size_standard_deviation: int,
    full_snapshot_count_mean: int,
    full_snapshot_count_standard_deviation: int,
    incremental_snapshot_size_mean: int,
    incremental_snapshot_size_standard_deviation: int,
    incremental_snapshot_count_mean: int,
    incremental_snapshot_count_standard_deviation: int,
    team_id: int,
    token: str,
    verbose: bool,
):
    # Generate session recording messages for a number, `count`, of sessions.
    # Each session is comprised of a sequence of snapshots, with the first
    # snapshot always being a full snapshot, and the remaining snapshots being a
    # mix of both full and incremental snapshots. The size of the snapshot data
    # is generated randomly, with the size of the full snapshot being generated
    # from a log-normal distribution with the given `full_snapshot_size_mean`
    # and `full_snapshot_size_standard_deviation`, and the size of the
    # incremental snapshots being generated from a log-normal distribution with
    # the given `incremental_snapshot_size_mean` and
    # `incremental_snapshot_size_standard_deviation`.
    #
    # Per session, the number of full snapshots is generated from a normal
    # distribution with the given `full_snapshot_count_mean` and
    # `full_snapshot_count_standard_deviation`. The number of incremental
    # snapshots is generated from a log-normal distribution with the given
    # `incremental_snapshot_count_mean` and
    # `incremental_snapshot_count_standard_deviation`.
    #
    # Snapshots that are larger than 900KB are split into chunks of 900KB each.
    # The max for Kafka is 1MB but because we are also adding additional
    # information to the message value that would be sent to Kafka, we leave
    # some padding room. The chunking information is included in the
    # `snapshot_data` property.
    #
    # {
    #     "uuid": "<a uuid>",
    #     "distinct_id": "<a uuid>",
    #     "ip": "10.32.42.12",
    #     "site_url": "https://app.posthog.com",
    #     "data": "<json encoded wrapper around the rrweb snapshot>",
    #     "team_id": team_id,
    #     "now": "<a datetime>"",
    #     "sent_at": "<a datetime>",
    #     "token": "<a uuid>",
    # }
    #
    # The `data` property is a JSON encoded wrapper around the rrweb snapshot
    # that looks like this:
    #
    # {
    #     "event": "$snapshot",
    #     "properties": {
    #         "distinct_id": "<a uuid>",
    #         "$session_id": "<a uuid>",
    #         "$window_id": "<a uuid>",
    #         "snapshot_data": {
    #             "chunk_id": "<a uuid>",
    #             "chunk_index": 0,
    #             "chunk_count": 10,
    #             "data": "<base64 encoded rrweb snapshot>",
    #             "compression": "gzip-base64",
    #             "has_full_snapshot": true,
    #         }
    #     }
    # }
    #
    # For the purpose of this benchmarking script, the rrweb snapshot data
    # attribute is completely opaque, and is only used to simulate the size
    # distribution of the messages.

    full_snapshot_count_samples = sample_log_normal_distribution(
        full_snapshot_count_mean, full_snapshot_count_standard_deviation, count
    )

    incremental_snapshot_count_samples = sample_log_normal_distribution(
        incremental_snapshot_count_mean,
        incremental_snapshot_count_standard_deviation,
        count,
    )

    full_snapshot_size_samples = sample_log_normal_distribution(
        full_snapshot_size_mean,
        full_snapshot_size_standard_deviation,
        max(full_snapshot_count_samples),
    )

    incremental_snapshot_size_samples = sample_log_normal_distribution(
        incremental_snapshot_size_mean,
        incremental_snapshot_size_standard_deviation,
        max(incremental_snapshot_count_samples),
    )

    now = faker.date_time()
    sent_at = faker.date_time()
    ip = faker.ipv4()
    site_url = faker.url()

    for full_snapshot_count, incremental_snapshot_count in zip(
        full_snapshot_count_samples, incremental_snapshot_count_samples
    ):
        session_id = str(uuid.uuid4())
        distinct_id = str(uuid.uuid4())

        # Use numpy to generate the number of full snapshots and incremental
        # from a log-normal distribution.
        if verbose:
            stderr.write(
                f"Generating session recording messages for session "
                f"{session_id} with an average of {full_snapshot_count_mean} "
                f"full snapshots with a standard deviation of "
                f"{full_snapshot_count_standard_deviation} and "
                f"an average of {incremental_snapshot_count_mean} "
                f"incremental snapshots with a standard deviation of "
                f"{incremental_snapshot_count_standard_deviation}"
                "\n"
            )

        if verbose:
            stderr.write(
                f"Generating session recording messages for session {session_id} "
                f"with {full_snapshot_count} full snapshots and {incremental_snapshot_count} "
                f"incremental snapshots"
                "/n"
            )

        # TODO: Intermingle full and incremental snapshots. At the moment we'll
        # just be procesing full snapshots then incremental snapshots which
        # isn't representative of real world usage.

        for full_snapshot_index, full_snapshot_size in enumerate(full_snapshot_size_samples[:full_snapshot_count]):
            full_snapshot_data = faker.pystr(min_chars=full_snapshot_size, max_chars=full_snapshot_size)

            # Split the full snapshot into chunks if it is larger than 900KB.
            full_snapshot_data_chunks = chunked(full_snapshot_data, 900000)

            for chunk_index, chunk in enumerate(full_snapshot_data_chunks):
                chunk_id = str(uuid.uuid4())
                chunk_count = len(full_snapshot_data_chunks)

                snapshot_data = {
                    "chunk_id": chunk_id,
                    "chunk_index": chunk_index,
                    "chunk_count": chunk_count,
                    "data": chunk,
                    "compression": "gzip-base64",
                    "has_full_snapshot": full_snapshot_index == 0,
                }

                data = {
                    "event": "$snapshot",
                    "properties": {
                        "distinct_id": distinct_id,
                        "session_id": session_id,
                        "window_id": session_id,
                        "snapshot_data": snapshot_data,
                    },
                }

                message = {
                    "uuid": str(uuid.uuid4()),
                    "distinct_id": distinct_id,
                    "ip": ip,
                    "site_url": site_url,
                    "data": json.dumps(data),
                    "team_id": team_id,
                    "now": now.isoformat(),
                    "sent_at": sent_at.isoformat(),
                    "token": token,
                }

                stdout.write(json.dumps(message))
                stdout.write("\n")

        for incremental_snapshot_size in incremental_snapshot_size_samples[:incremental_snapshot_count]:
            incremental_snapshot_data = faker.pystr(
                min_chars=incremental_snapshot_size, max_chars=incremental_snapshot_size
            )

            # Split the incremental snapshot into chunks if it is larger than
            # 900KB.
            incremental_snapshot_data_chunks = chunked(incremental_snapshot_data, 900000)

            for chunk_index, chunk in enumerate(incremental_snapshot_data_chunks):
                chunk_id = str(uuid.uuid4())
                chunk_count = len(incremental_snapshot_data_chunks)

                snapshot_data = {
                    "chunk_id": chunk_id,
                    "chunk_index": chunk_index,
                    "chunk_count": chunk_count,
                    "data": chunk,
                    "compression": "gzip-base64",
                    "has_full_snapshot": False,
                }

                data = {
                    "event": "$snapshot",
                    "properties": {
                        "distinct_id": distinct_id,
                        "session_id": session_id,
                        # TODO: handle multiple windows
                        "window_id": session_id,
                        "snapshot_data": snapshot_data,
                    },
                }

                message = {
                    "uuid": str(uuid.uuid4()),
                    "distinct_id": distinct_id,
                    "ip": ip,
                    "site_url": site_url,
                    "data": json.dumps(data),
                    "team_id": team_id,
                    "now": now.isoformat(),
                    "sent_at": sent_at.isoformat(),
                    "token": token,
                }

                stdout.write(json.dumps(message))
                stdout.write("\n")


def main():
    """
    Parse the command line arguments using `get_parser`, generate the snapshot messages, and print
    them out to stdout as a single JSON object per line. We also initialize
    Faker and numpy to ensure that the random number generator is seeded with a
    constant.
    """

    parser = get_parser()
    args = parser.parse_args()

    Faker.seed(args.seed_value)
    faker = Faker()

    numpy.random.seed(args.seed_value)

    generate_snapshot_messages(
        faker=faker,
        count=args.count,
        full_snapshot_size_mean=args.full_snapshot_size_mean,
        full_snapshot_size_standard_deviation=args.full_snapshot_size_standard_deviation,
        full_snapshot_count_mean=args.full_snapshot_count_mean,
        full_snapshot_count_standard_deviation=args.full_snapshot_count_standard_deviation,
        incremental_snapshot_size_mean=args.incremental_snapshot_size_mean,
        incremental_snapshot_size_standard_deviation=args.incremental_snapshot_size_standard_deviation,
        incremental_snapshot_count_mean=args.incremental_snapshot_count_mean,
        incremental_snapshot_count_standard_deviation=args.incremental_snapshot_count_standard_deviation,
        team_id=args.team_id,
        token=args.token,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
