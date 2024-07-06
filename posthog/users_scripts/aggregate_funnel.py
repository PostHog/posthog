#!/usr/bin/python3

import sys

N_ARGS = 4

def parse_args(line):
    t1 = line.find("\t")
    num_steps = int(line[:t1])
    t2 = line.find("\t", t1 + 1)
    conversion_window_limit = int(line[t1 + 1:t2])
    t3 = line.find("\t", t2 + 1)
    breakdown_attribution_type = line[t2 + 1:t3]
    return num_steps, conversion_window_limit, breakdown_attribution_type, eval(line[t3 + 1:])


# 60\t[(1719535134.119179,(1,0)),(1719988603.504339,(1,0)),(1720155830.04705,(1,0))]
# Funnel is ordered, assume no time limit for now
# Optimizations - tuple into a bitmask
def parse_user_aggregation(num_steps, conversion_window_limit, breakdown_attribution_type, timestamp_and_steps):
    next_index = 1
    for timestamp, steps in timestamp_and_steps:
        if next_index in steps:
            next_index += 1
            if next_index > num_steps:
                break
    if next_index > 1:
        print(next_index - 2)


# each one can be multiple steps here
# it only matters when they entered the funnel - you can propagate the time from the previous step when you update
def parse_user_aggregation_with_conversion_window(num_steps, conversion_window_limit, breakdown_attribution_type, timestamp_and_steps):
    # an array of when the user entered the funnel
    entered_timestamp = [0] * (num_steps + 1)

    for timestamp, steps in timestamp_and_steps:
        # iterate the steps in reverse so we don't count this event multiple times
        entered_timestamp[0] = timestamp
        for step in reversed(steps):
            if timestamp - entered_timestamp[step - 1] < conversion_window_limit:
                entered_timestamp[step] = entered_timestamp[step - 1]

        if entered_timestamp[num_steps] > 0:
            break

    for i in range(1, num_steps + 1):
        if entered_timestamp[i] == 0:
            print(i - 2)
            return
    print(num_steps - 1)

def parse_user_aggregation_with_conversion_window_and_breakdown_backup(num_steps, conversion_window_limit, breakdown_attribution_type, timestamp_and_steps):
    # an array of when the user entered the funnel
    entered_timestamp = [0] * (num_steps + 1)

    for timestamp, breakdown, steps in timestamp_and_steps:
        # iterate the steps in reverse so we don't count this event multiple times
        entered_timestamp[0] = timestamp
        for step in reversed(steps):
            if timestamp - entered_timestamp[step - 1] < conversion_window_limit:
                entered_timestamp[step] = entered_timestamp[step - 1]

        if entered_timestamp[num_steps] > 0:
            break

    for i in range(1, num_steps + 1):
        if entered_timestamp[i] == 0:
            print((i - 2, ""))
            return
    print((num_steps - 1, ""))

# each one can be multiple steps here
# it only matters when they entered the funnel - you can propagate the time from the previous step when you update
def parse_user_aggregation_with_conversion_window_and_breakdown(num_steps, conversion_window_limit, breakdown_attribution_type, timestamp_and_steps):
    # an array of when the user entered the funnel
    entered_timestamp = [(0, "")] * (num_steps + 1)

    # todo:
    # all matching breakdown types??? easiest to just do this separately for all breakdown types? what if multiple match?
    # step breakdown mode

    # This is the timestamp, breakdown value, and list of steps that it matches for each event
    for timestamp, breakdown, steps in timestamp_and_steps:
        # iterate the steps in reverse so we don't count this event multiple times
        entered_timestamp[0] = (timestamp, breakdown)
        for step in reversed(steps):
            if timestamp - entered_timestamp[step - 1][0] < conversion_window_limit:
                if breakdown_attribution_type == 'first_touch':
                    # If first touch, propagate the starting breakdown value
                    entered_timestamp[step] = entered_timestamp[step - 1]
                elif breakdown_attribution_type == 'last_touch':
                    # if last touch, always take the current value
                    entered_timestamp[step] = (entered_timestamp[step - 1][0], breakdown)

        if entered_timestamp[num_steps][0] > 0:
            break

    for i in range(1, num_steps + 1):
        if entered_timestamp[i][0] == 0:
            print((i - 2, entered_timestamp[i-1][1]))
            return
    print((num_steps - 1, entered_timestamp[num_steps][1]))

if __name__ == '__main__':
    for line in sys.stdin:
        parse_user_aggregation_with_conversion_window_and_breakdown(*parse_args(line))
        sys.stdout.flush()

"""
a = [(1719624249.503675,[1,2,4,5,6,7,8,9]),(1719624251.581988,[1,2,4,5,6,7,8,9]),(1719635907.573687,[1,2,4,5,6,7,8,9]),(1719635909.66015,[1,2,4,5,6,7,8,9]),(1719759818.990228,[1,2,4,5,6,7,8,9]),(1719759876.794997,[1,2,4,5,6,7,8,9]),(1719759878.856164,[1,2,4,5,6,7,8,9]),(1719803624.816091,[1,2,4,5,6,7,8,9]),(1719803809.529472,[1,2,4,5,6,7,8,9]),(1719803811.608051,[1,2,4,5,6,7,8,9]),(1719881651.587875,[3]),(1719886796.095619,[1,2,4,5,6,7,8,9]),(1719886798.206008,[1,2,4,5,6,7,8,9]),(1719968757.728293,[1,2,4,5,6,7,8,9]),(1719968784.265244,[1,2,4,5,6,7,8,9]),(1720048981.884196,[1,2,4,5,6,7,8,9]),(1720049173.969063,[1,2,4,5,6,7,8,9]),(1720067592.576889,[1,2,4,5,6,7,8,9]),(1720067656.454668,[1,2,4,5,6,7,8,9]),(1720067658.547188,[1,2,4,5,6,7,8,9]),(1720140655.805049,[1,2,4,5,6,7,8,9]),(1720140692.408485,[1,2,4,5,6,7,8,9])]
b = [(1719620572.818423,[1,2,4,5,6,7,8,9]),(1719620574.899927,[1,2,4,5,6,7,8,9]),(1719631883.411957,[1,2,4,5,6,7,8,9]),(1719631973.061015,[1,2,4,5,6,7,8,9]),(1719631975.132799,[1,2,4,5,6,7,8,9]),(1719640496.644576,[1,2,4,5,6,7,8,9]),(1719719866.343911,[1,2,4,5,6,7,8,9]),(1719719868.423301,[1,2,4,5,6,7,8,9]),(1719793284.221717,[1,2,4,5,6,7,8,9]),(1719793339.724518,[1,2,4,5,6,7,8,9]),(1719793341.809817,[1,2,4,5,6,7,8,9]),(1719812642.836549,[1,2,4,5,6,7,8,9]),(1719812644.925277,[1,2,4,5,6,7,8,9]),(1719883133.994423,[1,2,4,5,6,7,8,9]),(1719883166.099979,[1,2,4,5,6,7,8,9]),(1719903968.6994,[1,2,4,5,6,7,8,9]),(1719904040.485124,[1,2,4,5,6,7,8,9]),(1719904042.565526,[1,2,4,5,6,7,8,9]),(1719921915.765151,[1,2,4,5,6,7,8,9]),(1719921993.277794,[1,2,4,5,6,7,8,9]),(1719921995.367629,[1,2,4,5,6,7,8,9]),(1719969209.829488,[1,2,4,5,6,7,8,9]),(1719969245.269766,[1,2,4,5,6,7,8,9]),(1720048632.084256,[1,2,4,5,6,7,8,9]),(1720048770.592631,[1,2,4,5,6,7,8,9]),(1720048772.651474,[1,2,4,5,6,7,8,9]),(1720064684.711213,[3]),(1720122031.726969,[1,2,4,5,6,7,8,9]),(1720122184.822518,[1,2,4,5,6,7,8,9]),(1720150648.87242,[1,2,4,5,6,7,8,9]),(1720150650.943118,[1,2,4,5,6,7,8,9]),(1720213532.407721,[1,2,4,5,6,7,8,9]),(1720213752.785267,[1,2,4,5,6,7,8,9]),(1720213754.902257,[1,2,4,5,6,7,8,9])]
c = [(1719635561.134626,[1,2,4,5,6,7,8,9]),(1719635652.886371,[1,2,4,5,6,7,8,9]),(1719635654.998009,[1,2,4,5,6,7,8,9]),(1719704801.504247,[1,2,4,5,6,7,8,9]),(1719704803.538912,[1,2,4,5,6,7,8,9]),(1719761659.862534,[1,2,4,5,6,7,8,9]),(1719761661.963049,[1,2,4,5,6,7,8,9]),(1719774270.418871,[1,2,4,5,6,7,8,9]),(1719774334.869366,[1,2,4,5,6,7,8,9]),(1719774336.956447,[1,2,4,5,6,7,8,9]),(1719805718.249567,[1,2,4,5,6,7,8,9]),(1719855256.659775,[3]),(1719965295.624256,[1,2,4,5,6,7,8,9]),(1719965316.524137,[1,2,4,5,6,7,8,9]),(1719965318.610919,[1,2,4,5,6,7,8,9]),(1720069720.777595,[1,2,4,5,6,7,8,9]),(1720069722.826168,[1,2,4,5,6,7,8,9]),(1720148996.928905,[1,2,4,5,6,7,8,9])]
d = [(1719625454.157631,[1,2,4,5,6,7,8,9]),(1719625565.150241,[1,2,4,5,6,7,8,9]),(1719709543.012905,[1,2,4,5,6,7,8,9]),(1719709581.356587,[1,2,4,5,6,7,8,9]),(1719809058.323712,[1,2,4,5,6,7,8,9]),(1719809141.948789,[1,2,4,5,6,7,8,9]),(1719809143.991508,[1,2,4,5,6,7,8,9]),(1719881227.223798,[1,2,4,5,6,7,8,9]),(1719881229.332959,[1,2,4,5,6,7,8,9]),(1719892871.54215,[1,2,4,5,6,7,8,9]),(1719892871.57717,[1,2,4,5,6,7,8,9]),(1719892874.771596,[1,2,4,5,6,7,8,9]),(1719892889.074177,[3]),(1719966220.459407,[1,2,4,5,6,7,8,9]),(1719966307.773201,[1,2,4,5,6,7,8,9]),(1719966309.880214,[1,2,4,5,6,7,8,9]),(1719979818.866997,[1,2,4,5,6,7,8,9]),(1719979852.84949,[1,2,4,5,6,7,8,9]),(1719979854.94106,[1,2,4,5,6,7,8,9]),(1719979859.461516,[1,2,4,5,6,7,8,9]),(1720059207.81028,[1,2,4,5,6,7,8,9]),(1720059399.485881,[1,2,4,5,6,7,8,9]),(1720059401.521919,[1,2,4,5,6,7,8,9]),(1720119108.681961,[1,2,4,5,6,7,8,9]),(1720119247.145133,[1,2,4,5,6,7,8,9]),(1720119249.257503,[1,2,4,5,6,7,8,9]),(1720119249.579358,[1,2,4,5,6,7,8,9]),(1720119251.622174,[1,2,4,5,6,7,8,9]),(1720150331.046157,[1,2,4,5,6,7,8,9]),(1720150459.12818,[1,2,4,5,6,7,8,9])]
e = [(1719622680.227124,[1,2,4,5,6,7,8,9]),(1719622806.287646,[1,2,4,5,6,7,8,9]),(1719711273.965522,[1,2,4,5,6,7,8,9]),(1719711477.902064,[1,2,4,5,6,7,8,9]),(1719794304.252785,[1,2,4,5,6,7,8,9]),(1719794509.71504,[1,2,4,5,6,7,8,9]),(1719794511.818692,[1,2,4,5,6,7,8,9]),(1719794514.422225,[1,2,4,5,6,7,8,9]),(1719794516.498155,[1,2,4,5,6,7,8,9]),(1719794518.363868,[1,2,4,5,6,7,8,9]),(1719812619.340187,[1,2,4,5,6,7,8,9]),(1719812777.266787,[1,2,4,5,6,7,8,9]),(1719819637.056956,[1,2,4,5,6,7,8,9]),(1719819748.392751,[1,2,4,5,6,7,8,9]),(1719819750.452626,[1,2,4,5,6,7,8,9]),(1719893726.876636,[1,2,4,5,6,7,8,9]),(1720057314.415114,[1,2,4,5,6,7,8,9]),(1720057360.551437,[1,2,4,5,6,7,8,9]),(1720064794.532582,[1,2,4,5,6,7,8,9]),(1720064796.628956,[1,2,4,5,6,7,8,9]),(1720150679.487001,[3]),(1720152449.296229,[1,2,4,5,6,7,8,9]),(1720152520.132648,[1,2,4,5,6,7,8,9]),(1720152522.257136,[1,2,4,5,6,7,8,9]),(1720152526.129531,[1,2,4,5,6,7,8,9]),(1720152528.222314,[1,2,4,5,6,7,8,9]),(1720163131.038693,[1,2,4,5,6,7,8,9]),(1720163133.119918,[1,2,4,5,6,7,8,9])]
"""
