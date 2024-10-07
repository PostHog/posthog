#!/usr/bin/python3
import sys

from aggregate_funnel_trends import parse_args, calculate_funnel_trends_from_user_events

if __name__ == "__main__":
    for line in sys.stdin:
        calculate_funnel_trends_from_user_events(*parse_args(line))
        sys.stdout.flush()
