#!/usr/bin/python3
import sys
from dataclasses import dataclass, replace
from typing import Any
from collections.abc import Sequence
import json


def parse_args(line):
    args = json.loads(line)
    return [
        int(args["from_step"]),
        int(args["num_steps"]),
        int(args["conversion_window_limit"]),
        str(args["breakdown_attribution_type"]),
        str(args["funnel_order_type"]),
        args["prop_vals"],  # Array(Array(String))
        args["value"],  # Array(Tuple(Nullable(Float64), Nullable(DateTime), Array(String), Array(Int8)))
    ]


@dataclass(frozen=True)
class EnteredTimestamp:
    timestamp: Any
    timings: Any


# each one can be multiple steps here
# it only matters when they entered the funnel - you can propagate the time from the previous step when you update
# This function is defined for Clickhouse in user_defined_functions.xml along with types
# num_steps is the total number of steps in the funnel
# conversion_window_limit is in seconds
# events is a array of tuples of (timestamp, breakdown, [steps])
# steps is an array of integers which represent the steps that this event qualifies for. it looks like [1,3,5,6].
# negative integers represent an exclusion on that step. each event is either all exclusions or all steps.
def calculate_funnel_trends_from_user_events(
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
                # Special code to handle the first step
                # Potential Optimization: we could skip tracking here if the user has already completed the funnel for this interval
                if step == 1:
                    entered_timestamp = [default_entered_timestamp] * (num_steps + 1)
                    # Set the interval start at 0, which is what we want to return if this works.
                    # For strict funnels, we need to track if the "from_step" has been hit
                    # Abuse the timings field on the 0th index entered_timestamp to have the elt True if we have
                    entered_timestamp[0] = EnteredTimestamp(interval_start, [True] if from_step == 0 else [])
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
                                    results[entered_timestamp[0].timestamp] = (1, prop_val)
                                    list_of_entered_timestamps.remove(entered_timestamp)
                                # If we have hit the from_step threshold, record it (abuse the timings field)
                                elif step == from_step + 1:
                                    entered_timestamp[0].timings.append(True)

            # At the end of the event, clear all steps that weren't done by that event
            if funnel_order_type == "strict":
                for entered_timestamp in list_of_entered_timestamps[:]:
                    for i in range(1, len(entered_timestamp)):
                        if i not in steps:
                            entered_timestamp[i] = default_entered_timestamp

        # At this point, everything left in entered_timestamps is a failure, if it has made it to from_step
        for entered_timestamp in list_of_entered_timestamps:
            if entered_timestamp[0].timestamp not in results and len(entered_timestamp[0].timings) > 0:
                results[entered_timestamp[0].timestamp] = (-1, prop_val)

    [loop_prop_val(prop_val) for prop_val in prop_vals]
    result = [(interval_start, success_bool, prop_val) for interval_start, (success_bool, prop_val) in results.items()]
    print(json.dumps({"result": result}), end="\n")  # noqa: T201


if __name__ == "__main__":
    for line in sys.stdin:
        calculate_funnel_trends_from_user_events(*parse_args(line))
        sys.stdout.flush()
