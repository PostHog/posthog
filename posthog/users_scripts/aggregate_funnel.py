#!/usr/bin/python3

import sys
from dataclasses import dataclass, replace
from itertools import groupby, permutations
from typing import Any, List

N_ARGS = 5

def parse_args(line):
    t1 = line.find("\t")
    num_steps = int(line[:t1])
    t2 = line.find("\t", t1 + 1)
    conversion_window_limit = int(line[t1 + 1:t2])
    t3 = line.find("\t", t2 + 1)
    breakdown_attribution_type = line[t2 + 1:t3]
    t4 = line.find("\t", t3 + 1)
    prop_vals = eval(line[t3 + 1:t4])
    return num_steps, conversion_window_limit, breakdown_attribution_type, prop_vals, eval(line[t4 + 1:])

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
# events is a array of tuples of (timestamp, breakdown, [
def parse_user_aggregation_with_conversion_window_and_breakdown(num_steps: int, conversion_window_limit_seconds: int, breakdown_attribution_type: str, prop_vals: List[any], events: List[any]):

    # all matching breakdown types??? easiest to just do this separately for all breakdown types? what if multiple match?
    # step breakdown mode
    breakdown_step = int(breakdown_attribution_type[5:]) if breakdown_attribution_type.startswith('step_') else None

    # This is the timestamp, breakdown value, and list of steps that it matches for each
    results = []

    def loop_prop_val(prop_val):
        # an array of when the user entered the funnel
        # entered_timestamp = [(0, "", [])] * (num_steps + 1)
        entered_timestamp: List[EnteredTimestamp] = [EnteredTimestamp(0, [])] * (num_steps + 1)

        def add_result(i):
            final = entered_timestamp[i]
            results.append(f"({i - 1}, {breakdown_to_single_quoted_string(prop_val)}, {str([final.timings[i] - final.timings[i - 1] for i in range(1, i)])})")

        filtered_events = ((timestamp, breakdown, steps) for (timestamp, breakdown, steps) in events if breakdown == prop_val) if breakdown_attribution_type == 'all_events' else events
        for timestamp, events_group in groupby(filtered_events, key=lambda x: x[0]):
            entered_timestamp[0] = EnteredTimestamp(timestamp, [])
            entered_timestamps = []
            for events_group_perm in permutations(events_group):
                entered_timestamp = [x for x in entered_timestamp]
                entered_timestamps.append(entered_timestamp)
                for (timestamp, breakdown, steps) in events_group_perm:
                    # iterate the steps in reverse so we don't count this event multiple times
                    for step in reversed(steps):
                        # if we are in a window and if we don't already have a matching event with the same entered timestamp:
                        # if we already have a matching event here with the same entered timestamp, don't do

                        exclusion = False
                        if step < 0:
                            exclusion = True
                            step = -step

                        in_match_window = timestamp - entered_timestamp[step - 1].timestamp <= conversion_window_limit_seconds
                        already_reached_this_step_with_same_entered_timestamp = entered_timestamp[step].timestamp == entered_timestamp[step - 1].timestamp

                        if in_match_window and not already_reached_this_step_with_same_entered_timestamp:
                            if exclusion:
                                results.append(f"(-1, {breakdown_to_single_quoted_string(prop_val)}, [])")
                                return
                            is_unmatched_step_attribution = breakdown_step is not None and step == breakdown_step - 1 and prop_val != breakdown
                            if not is_unmatched_step_attribution:
                                entered_timestamp[step] = replace(entered_timestamp[step - 1], timings=entered_timestamp[step - 1].timings + [timestamp])
            new_entered_timestamp = [None] * (num_steps + 1)
            for i in range(len(new_entered_timestamp)):
                new_entered_timestamp[i] = max((entered_timestamp[i] for entered_timestamp in entered_timestamps), key=lambda x: x.timestamp)
            entered_timestamp = new_entered_timestamp

            if entered_timestamp[num_steps].timestamp > 0:
                add_result(num_steps)
                return

        for i in range(1, num_steps + 1):
            if entered_timestamp[i].timestamp == 0:
                add_result(i - 1)
                return

        add_result(num_steps)
        return

    [loop_prop_val(prop_val) for prop_val in prop_vals]
    print(f"[{','.join(results)}]")

if __name__ == '__main__':
    for line in sys.stdin:
        parse_user_aggregation_with_conversion_window_and_breakdown(*parse_args(line))
        sys.stdout.flush()

def test():
    y = [[(1577973600, '', [1]), (1577980800, '', [2]), (1577984400, '', [3])],
     [(1577880000, '', [1]), (1577883600, '', [2]), (1577890800, '', [3])],
     [(1577973600, '', [1]), (1577980800, '', [2])]]

    for x in y:
        parse_user_aggregation_with_conversion_window_and_breakdown(3, 1209600, 'first_touch', [''], x)

    """
    a = [(1719624249.503675,[1,2,4,5,6,7,8,9]),(1719624251.581988,[1,2,4,5,6,7,8,9]),(1719635907.573687,[1,2,4,5,6,7,8,9]),(1719635909.66015,[1,2,4,5,6,7,8,9]),(1719759818.990228,[1,2,4,5,6,7,8,9]),(1719759876.794997,[1,2,4,5,6,7,8,9]),(1719759878.856164,[1,2,4,5,6,7,8,9]),(1719803624.816091,[1,2,4,5,6,7,8,9]),(1719803809.529472,[1,2,4,5,6,7,8,9]),(1719803811.608051,[1,2,4,5,6,7,8,9]),(1719881651.587875,[3]),(1719886796.095619,[1,2,4,5,6,7,8,9]),(1719886798.206008,[1,2,4,5,6,7,8,9]),(1719968757.728293,[1,2,4,5,6,7,8,9]),(1719968784.265244,[1,2,4,5,6,7,8,9]),(1720048981.884196,[1,2,4,5,6,7,8,9]),(1720049173.969063,[1,2,4,5,6,7,8,9]),(1720067592.576889,[1,2,4,5,6,7,8,9]),(1720067656.454668,[1,2,4,5,6,7,8,9]),(1720067658.547188,[1,2,4,5,6,7,8,9]),(1720140655.805049,[1,2,4,5,6,7,8,9]),(1720140692.408485,[1,2,4,5,6,7,8,9])]
    b = [(1719620572.818423,[1,2,4,5,6,7,8,9]),(1719620574.899927,[1,2,4,5,6,7,8,9]),(1719631883.411957,[1,2,4,5,6,7,8,9]),(1719631973.061015,[1,2,4,5,6,7,8,9]),(1719631975.132799,[1,2,4,5,6,7,8,9]),(1719640496.644576,[1,2,4,5,6,7,8,9]),(1719719866.343911,[1,2,4,5,6,7,8,9]),(1719719868.423301,[1,2,4,5,6,7,8,9]),(1719793284.221717,[1,2,4,5,6,7,8,9]),(1719793339.724518,[1,2,4,5,6,7,8,9]),(1719793341.809817,[1,2,4,5,6,7,8,9]),(1719812642.836549,[1,2,4,5,6,7,8,9]),(1719812644.925277,[1,2,4,5,6,7,8,9]),(1719883133.994423,[1,2,4,5,6,7,8,9]),(1719883166.099979,[1,2,4,5,6,7,8,9]),(1719903968.6994,[1,2,4,5,6,7,8,9]),(1719904040.485124,[1,2,4,5,6,7,8,9]),(1719904042.565526,[1,2,4,5,6,7,8,9]),(1719921915.765151,[1,2,4,5,6,7,8,9]),(1719921993.277794,[1,2,4,5,6,7,8,9]),(1719921995.367629,[1,2,4,5,6,7,8,9]),(1719969209.829488,[1,2,4,5,6,7,8,9]),(1719969245.269766,[1,2,4,5,6,7,8,9]),(1720048632.084256,[1,2,4,5,6,7,8,9]),(1720048770.592631,[1,2,4,5,6,7,8,9]),(1720048772.651474,[1,2,4,5,6,7,8,9]),(1720064684.711213,[3]),(1720122031.726969,[1,2,4,5,6,7,8,9]),(1720122184.822518,[1,2,4,5,6,7,8,9]),(1720150648.87242,[1,2,4,5,6,7,8,9]),(1720150650.943118,[1,2,4,5,6,7,8,9]),(1720213532.407721,[1,2,4,5,6,7,8,9]),(1720213752.785267,[1,2,4,5,6,7,8,9]),(1720213754.902257,[1,2,4,5,6,7,8,9])]
    c = [(1719635561.134626,[1,2,4,5,6,7,8,9]),(1719635652.886371,[1,2,4,5,6,7,8,9]),(1719635654.998009,[1,2,4,5,6,7,8,9]),(1719704801.504247,[1,2,4,5,6,7,8,9]),(1719704803.538912,[1,2,4,5,6,7,8,9]),(1719761659.862534,[1,2,4,5,6,7,8,9]),(1719761661.963049,[1,2,4,5,6,7,8,9]),(1719774270.418871,[1,2,4,5,6,7,8,9]),(1719774334.869366,[1,2,4,5,6,7,8,9]),(1719774336.956447,[1,2,4,5,6,7,8,9]),(1719805718.249567,[1,2,4,5,6,7,8,9]),(1719855256.659775,[3]),(1719965295.624256,[1,2,4,5,6,7,8,9]),(1719965316.524137,[1,2,4,5,6,7,8,9]),(1719965318.610919,[1,2,4,5,6,7,8,9]),(1720069720.777595,[1,2,4,5,6,7,8,9]),(1720069722.826168,[1,2,4,5,6,7,8,9]),(1720148996.928905,[1,2,4,5,6,7,8,9])]
    d = [(1719625454.157631,[1,2,4,5,6,7,8,9]),(1719625565.150241,[1,2,4,5,6,7,8,9]),(1719709543.012905,[1,2,4,5,6,7,8,9]),(1719709581.356587,[1,2,4,5,6,7,8,9]),(1719809058.323712,[1,2,4,5,6,7,8,9]),(1719809141.948789,[1,2,4,5,6,7,8,9]),(1719809143.991508,[1,2,4,5,6,7,8,9]),(1719881227.223798,[1,2,4,5,6,7,8,9]),(1719881229.332959,[1,2,4,5,6,7,8,9]),(1719892871.54215,[1,2,4,5,6,7,8,9]),(1719892871.57717,[1,2,4,5,6,7,8,9]),(1719892874.771596,[1,2,4,5,6,7,8,9]),(1719892889.074177,[3]),(1719966220.459407,[1,2,4,5,6,7,8,9]),(1719966307.773201,[1,2,4,5,6,7,8,9]),(1719966309.880214,[1,2,4,5,6,7,8,9]),(1719979818.866997,[1,2,4,5,6,7,8,9]),(1719979852.84949,[1,2,4,5,6,7,8,9]),(1719979854.94106,[1,2,4,5,6,7,8,9]),(1719979859.461516,[1,2,4,5,6,7,8,9]),(1720059207.81028,[1,2,4,5,6,7,8,9]),(1720059399.485881,[1,2,4,5,6,7,8,9]),(1720059401.521919,[1,2,4,5,6,7,8,9]),(1720119108.681961,[1,2,4,5,6,7,8,9]),(1720119247.145133,[1,2,4,5,6,7,8,9]),(1720119249.257503,[1,2,4,5,6,7,8,9]),(1720119249.579358,[1,2,4,5,6,7,8,9]),(1720119251.622174,[1,2,4,5,6,7,8,9]),(1720150331.046157,[1,2,4,5,6,7,8,9]),(1720150459.12818,[1,2,4,5,6,7,8,9])]
    e = [(1719622680.227124,[1,2,4,5,6,7,8,9]),(1719622806.287646,[1,2,4,5,6,7,8,9]),(1719711273.965522,[1,2,4,5,6,7,8,9]),(1719711477.902064,[1,2,4,5,6,7,8,9]),(1719794304.252785,[1,2,4,5,6,7,8,9]),(1719794509.71504,[1,2,4,5,6,7,8,9]),(1719794511.818692,[1,2,4,5,6,7,8,9]),(1719794514.422225,[1,2,4,5,6,7,8,9]),(1719794516.498155,[1,2,4,5,6,7,8,9]),(1719794518.363868,[1,2,4,5,6,7,8,9]),(1719812619.340187,[1,2,4,5,6,7,8,9]),(1719812777.266787,[1,2,4,5,6,7,8,9]),(1719819637.056956,[1,2,4,5,6,7,8,9]),(1719819748.392751,[1,2,4,5,6,7,8,9]),(1719819750.452626,[1,2,4,5,6,7,8,9]),(1719893726.876636,[1,2,4,5,6,7,8,9]),(1720057314.415114,[1,2,4,5,6,7,8,9]),(1720057360.551437,[1,2,4,5,6,7,8,9]),(1720064794.532582,[1,2,4,5,6,7,8,9]),(1720064796.628956,[1,2,4,5,6,7,8,9]),(1720150679.487001,[3]),(1720152449.296229,[1,2,4,5,6,7,8,9]),(1720152520.132648,[1,2,4,5,6,7,8,9]),(1720152522.257136,[1,2,4,5,6,7,8,9]),(1720152526.129531,[1,2,4,5,6,7,8,9]),(1720152528.222314,[1,2,4,5,6,7,8,9]),(1720163131.038693,[1,2,4,5,6,7,8,9]),(1720163133.119918,[1,2,4,5,6,7,8,9])]
    for z in (a,b,c,d,e):
        with_breakdown = [(x[0], '', x[1]) for x in z]
        parse_user_aggregation_with_conversion_window_and_breakdown(9, 9000000, 'first_touch', with_breakdown)
    """