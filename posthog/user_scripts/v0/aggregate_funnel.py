#!/usr/bin/python3
import json
import sys
from dataclasses import dataclass, replace
from itertools import groupby, permutations
from typing import Any, cast
from collections.abc import Sequence


def parse_args(line):
    args = json.loads(line)
    return [
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
def calculate_funnel_from_user_events(
    num_steps: int,
    conversion_window_limit_seconds: int,
    breakdown_attribution_type: str,
    funnel_order_type: str,
    prop_vals: list[Any],
    events: Sequence[tuple[float, list[str] | int | str, list[int]]],
):
    default_entered_timestamp = EnteredTimestamp(0, [])
    max_step = [0, default_entered_timestamp]
    # If the attribution mode is a breakdown step, set this to the integer that represents that step
    breakdown_step = int(breakdown_attribution_type[5:]) if breakdown_attribution_type.startswith("step_") else None

    # This function returns an Array. We build up an array of strings to return here.
    results: list[tuple[int, Any, list[float]]] = []

    # Process an event. If this hits an exclusion, return False, else return True.
    def process_event(timestamp, breakdown, steps, *, entered_timestamp, prop_val) -> bool:
        # iterate the steps in reverse so we don't count this event multiple times
        for step in reversed(steps):
            exclusion = False
            if step < 0:
                exclusion = True
                step = -step

            in_match_window = timestamp - entered_timestamp[step - 1].timestamp <= conversion_window_limit_seconds
            already_reached_this_step_with_same_entered_timestamp = (
                entered_timestamp[step].timestamp == entered_timestamp[step - 1].timestamp
            )

            if in_match_window and not already_reached_this_step_with_same_entered_timestamp:
                if exclusion:
                    results.append((-1, prop_val, []))
                    return False
                is_unmatched_step_attribution = (
                    breakdown_step is not None and step == breakdown_step - 1 and prop_val != breakdown
                )
                if not is_unmatched_step_attribution:
                    entered_timestamp[step] = replace(
                        entered_timestamp[step - 1], timings=[*entered_timestamp[step - 1].timings, timestamp]
                    )
                if step > max_step[0]:
                    max_step[:] = (step, entered_timestamp[step])

        if funnel_order_type == "strict":
            for i in range(len(entered_timestamp)):
                if i not in steps:
                    entered_timestamp[i] = default_entered_timestamp

        return True

    # We call this for each possible breakdown value.
    def loop_prop_val(prop_val):
        # an array of when the user entered the funnel
        # entered_timestamp = [(0, "", [])] * (num_steps + 1)
        max_step[:] = [0, default_entered_timestamp]
        entered_timestamp: list[EnteredTimestamp] = [default_entered_timestamp] * (num_steps + 1)

        def add_max_step():
            i = cast(int, max_step[0])
            final = cast(EnteredTimestamp, max_step[1])
            results.append((i - 1, prop_val, [final.timings[i] - final.timings[i - 1] for i in range(1, i)]))

        filtered_events = (
            ((timestamp, breakdown, steps) for (timestamp, breakdown, steps) in events if breakdown == prop_val)
            if breakdown_attribution_type == "all_events"
            else events
        )
        for timestamp, events_with_same_timestamp_iterator in groupby(filtered_events, key=lambda x: x[0]):
            events_with_same_timestamp = tuple(events_with_same_timestamp_iterator)
            entered_timestamp[0] = EnteredTimestamp(timestamp, [])
            if len(events_with_same_timestamp) == 1:
                if not process_event(
                    *events_with_same_timestamp[0], entered_timestamp=entered_timestamp, prop_val=prop_val
                ):
                    return
            else:
                # This is a special case for events with the same timestamp
                # We play all of their permutations and most generously take the ones that advanced the furthest
                # This has quite bad performance, and can probably be optimized through clever but annoying logic
                # but shouldn't be hit too often
                entered_timestamps = []
                for events_group_perm in permutations(events_with_same_timestamp):
                    entered_timestamps.append(list(entered_timestamp))
                    for event in events_group_perm:
                        if not process_event(*event, entered_timestamp=entered_timestamps[-1], prop_val=prop_val):
                            # If any of the permutations hits an exclusion, we exclude this user.
                            # This isn't an important implementation detail and we could do something smarter here.
                            return
                for i in range(len(entered_timestamp)):
                    entered_timestamp[i] = max((x[i] for x in entered_timestamps), key=lambda x: x.timestamp)

            # If we have hit the goal, we can terminate early
            if entered_timestamp[num_steps].timestamp > 0:
                add_max_step()
                return

        # Find the furthest step we have made it to and print it
        add_max_step()
        return

    [loop_prop_val(prop_val) for prop_val in prop_vals]
    print(json.dumps({"result": results}), end="\n")  # noqa: T201


if __name__ == "__main__":
    for line in sys.stdin:
        calculate_funnel_from_user_events(*parse_args(line))
        sys.stdout.flush()
