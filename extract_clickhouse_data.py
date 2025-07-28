#!/usr/bin/env python3
import argparse
import json
import os
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import unquote

from clickhouse_driver import Client


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-id", required=True, type=str)
    parser.add_argument("--timestamp", required=True, type=str)
    parser.add_argument("--output-path", required=True, type=str)
    parser.add_argument("--prod", action="store_true", help="Use local ClickHouse")
    parser.add_argument("--team-id", required=False, type=int)
    args = parser.parse_args()
    # +-1 day from timestamp
    timestamp_str = unquote(args.timestamp) if "%" in args.timestamp else args.timestamp
    base_timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    start_timestamp = base_timestamp - timedelta(days=1)
    end_timestamp = base_timestamp + timedelta(days=1)
    if args.prod:
        host = os.environ["CLICKHOUSE_US_HOST_READONLY"]
        user = os.environ["CLICKHOUSE_US_USER_READONLY"]
        password = os.environ["CLICKHOUSE_US_PASS_READONLY"]
        team_id = args.team_id if args.team_id else 2
    else:
        host = "localhost"
        user = "default"
        password = ""
        team_id = args.team_id if args.team_id else 1
    # Get data from US ClickHouse
    client = Client(
        host=host,
        user=user,
        password=password,
        secure=True if args.prod else False,
        verify=False,
    )
    query = """
    SELECT
        event,
        timestamp,
        team_id,
        arrayFilter (kv -> startsWith (kv .1, '$ai_'), JSONExtractKeysAndValues (properties, 'String')) AS ai_props
    FROM
        events
    WHERE
        event IN ('$ai_span', '$ai_generation', '$ai_metric', '$ai_feedback', '$ai_trace')
        AND JSONExtractString (properties, '$ai_trace_id') = %(trace_id)s
        AND timestamp >= %(start_timestamp)s
        AND timestamp <= %(end_timestamp)s
        AND team_id = %(team_id)s
    ORDER BY timestamp
    """
    results = client.execute(
        query,
        {
            "trace_id": args.trace_id,
            "start_timestamp": start_timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "end_timestamp": end_timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "team_id": team_id,
        },
    )
    # Store data as an array of JSON objects
    output_data: list[dict[str, Any]] = []
    for row in results:
        record = {
            "event": row[0],
            "timestamp": row[1].isoformat(),
            "team_id": row[2],
        }
        for key, value in row[3]:
            record[key] = value
        output_data.append(record)
    with open(args.output_path, "w") as f:
        json.dump(output_data, f)


if __name__ == "__main__":
    main()
