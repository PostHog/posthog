#!/usr/bin/python3
import ast
import sys
from dataclasses import dataclass, replace
from typing import Any
from collections.abc import Callable
from collections.abc import Sequence


def parse_args(line):
    arg_functions: list[Callable] = [int, int, int, str, str, ast.literal_eval, ast.literal_eval]
    args = []
    start = 0
    for i in range(len(arg_functions) - 1):
        end = line.find("\t", start)
        args.append(arg_functions[i](line[start:end]))
        start = end + 1
    args.append(arg_functions[-1](line[start:]))
    return args


@dataclass(frozen=True)
class EnteredTimestamp:
    timestamp: Any
    timings: Any


def breakdown_to_single_quoted_string(breakdown):
    if isinstance(breakdown, str):
        return "'" + breakdown.replace("'", r"\'") + "'"
    if isinstance(breakdown, int):
        return breakdown
    if isinstance(breakdown, list):
        if not breakdown:
            return "[]"
        if isinstance(breakdown[0], str):
            return "['" + "','".join([x.replace("'", r"\'") for x in breakdown]) + "']"
        if isinstance(breakdown[0], int):
            return str(breakdown)
    raise Exception()


# each one can be multiple steps here
# it only matters when they entered the funnel - you can propagate the time from the previous step when you update
# This function is defined for Clickhouse in test_function.xml along with types
# num_steps is the total number of steps in the funnel
# conversion_window_limit is in seconds
# events is a array of tuples of (timestamp, breakdown, [steps])
# steps is an array of integers which represent the steps that this event qualifies for. it looks like [1,3,5,6].
# negative integers represent an exclusion on that step. each event is either all exclusions or all steps.
def parse_user_aggregation_with_conversion_window_and_breakdown(
    from_step: int,
    num_steps: int,
    conversion_window_limit_seconds: int,
    breakdown_attribution_type: str,
    funnel_order_type: str,
    prop_vals: list[Any],
    events: Sequence[tuple[float, int, list[str] | int | str, list[int]]],
):
    default_entered_timestamp = EnteredTimestamp(0, [])
    # If the attribution mode is a breakdown step, set this to the integer that represents that step
    breakdown_step = int(breakdown_attribution_type[5:]) if breakdown_attribution_type.startswith("step_") else None

    # Results is a map of start intervals to success or failure. If an interval isn't here, it means the
    # user didn't enter
    results = {}

    # We call this for each possible breakdown value.
    def loop_prop_val(prop_val):
        # we need to track every distinct entry into the funnel through to the end
        filtered_events = (
            (
                (timestamp, interval_start, breakdown, steps)
                for (timestamp, interval_start, breakdown, steps) in events
                if breakdown == prop_val
            )
            if breakdown_attribution_type == "all_events"
            else events
        )
        list_of_entered_timestamps = []

        for timestamp, interval_start, breakdown, steps in filtered_events:
            for step in reversed(steps):
                exclusion = False
                if step < 0:
                    exclusion = True
                    step = -step
                # special code to handle the first step
                if step == 1:
                    entered_timestamp = [default_entered_timestamp] * (num_steps + 1)
                    # Put the interval start at 0, which is what we want to return if this works
                    # could skip tracking here if the user has already completed the funnel for this interval
                    # what about exclusions?
                    entered_timestamp[0] = EnteredTimestamp(interval_start, [])
                    entered_timestamp[1] = EnteredTimestamp(timestamp, [timestamp])
                    list_of_entered_timestamps.append(entered_timestamp)
                else:
                    for entered_timestamp in list_of_entered_timestamps[:]:
                        in_match_window = (
                            timestamp - entered_timestamp[step - 1].timestamp <= conversion_window_limit_seconds
                        )
                        already_reached_this_step_with_same_entered_timestamp = (
                            entered_timestamp[step].timestamp == entered_timestamp[step - 1].timestamp
                        )
                        if in_match_window and not already_reached_this_step_with_same_entered_timestamp:
                            if exclusion:
                                # this is a complete failure, exclude this person, don't print anything, don't count
                                return False
                            is_unmatched_step_attribution = (
                                breakdown_step is not None and step == breakdown_step - 1 and prop_val != breakdown
                            )
                            if not is_unmatched_step_attribution:
                                entered_timestamp[step] = replace(
                                    entered_timestamp[step - 1],
                                    timings=[*entered_timestamp[step - 1].timings, timestamp],
                                )
                                # check if we have hit the goal. if we have, remove it from the list and add it to the successful_timestamps
                                if entered_timestamp[num_steps].timestamp > 0:
                                    results[entered_timestamp[0].timestamp] = 1
                                    list_of_entered_timestamps.remove(entered_timestamp)

        # At this point, everything left in entered_timestamps is a failure, if it has made it to from_step
        for entered_timestamp in list_of_entered_timestamps:
            if entered_timestamp[0].timestamp not in results and entered_timestamp[from_step + 1].timestamp > 0:
                results[entered_timestamp[0].timestamp] = 0

    # We don't support breakdowns atm - make this support breakdowns
    [loop_prop_val(prop_val) for prop_val in prop_vals]
    result_strings = [f"('{k}', {v})" for k, v in results.items()]
    print(f"[{','.join(result_strings)}]")  # noqa: T201


if __name__ == "__main__":
    for line in sys.stdin:
        parse_user_aggregation_with_conversion_window_and_breakdown(*parse_args(line))
        sys.stdout.flush()
