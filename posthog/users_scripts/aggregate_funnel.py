#!/usr/bin/python3

import sys


# 60\t[(1719535134.119179,(1,0)),(1719988603.504339,(1,0)),(1720155830.04705,(1,0))]
# Funnel is ordered, assume no time limit for now
# Optimizations - tuple into a bitmask
def parse_user_aggregation(line):
    t1 = line.find("\t")
    num_steps = int(line[:t1])
    t2 = line.find("\t", t1 + 1)
    conversion_window_limit = int(line[t1+1:t2])

    next_index = 1
    for timestamp, steps in eval(line[t2+1:]):
        if next_index in steps:
            next_index += 1
            if next_index > num_steps:
                break
    if next_index > 1:
        print(next_index - 2)

MAX_STEPS = 20

# each one can be multiple steps here
# it only matters when they entered the funnel - you can propagate the time from the previous step when you update
"""
def parse_user_aggregation_with_conversion_window(line):
    t = line.find("\t")
    conversion_window_limit = int(line[:t])
    next_index = 0
    steps = [0] * MAX_STEPS
    for timestamp, steps in eval(line[t+1:]):
        for i, step in enumerate(steps):
"""

if __name__ == '__main__':
    for line in sys.stdin:
        parse_user_aggregation(line)
        #print("Value " + line, end='')
        sys.stdout.flush()
