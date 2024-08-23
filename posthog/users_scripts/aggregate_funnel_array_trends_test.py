#!/usr/bin/python3

from aggregate_funnel_trends import parse_user_aggregation_with_conversion_window_and_breakdown, parse_args
import sys

if __name__ == "__main__":
    for line in sys.stdin:
        parse_user_aggregation_with_conversion_window_and_breakdown(*parse_args(line))
        sys.stdout.flush()
