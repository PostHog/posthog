#!/usr/bin/python3

from aggregate_funnel import parse_user_aggregation_with_conversion_window_and_breakdown, parse_args
import sys

if __name__ == "__main__":
    for line in sys.stdin:
        try:
            parse_user_aggregation_with_conversion_window_and_breakdown(*parse_args(line))
        except Exception as e:
            print(e, line)  # noqa: T201
        sys.stdout.flush()
