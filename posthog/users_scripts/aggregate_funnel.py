#!/usr/bin/python3

import sys


# [(1719535134.119179,(1,0)),(1719988603.504339,(1,0)),(1720155830.04705,(1,0))]
# Funnel is ordered, assume no time limit for now
# Optimizations - tuple into a bitmask
def parse_user_aggregation(line):
    next_index = 0
    for timestamp, steps in eval(line):
        if steps[next_index]:
            next_index += 1
            if next_index == len(steps):
                break
    if next_index > 0:
        print(next_index - 1)

if __name__ == '__main__':
    for line in sys.stdin:
        parse_user_aggregation(line)
        #print("Value " + line, end='')
        sys.stdout.flush()
