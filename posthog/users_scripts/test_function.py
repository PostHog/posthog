#!/usr/bin/python3

import sys

def parse_args(line):
    t1 = line.find("\t")
    num_steps = int(line[:t1])
    t2 = line.find("\t", t1 + 1)
    conversion_window_limit = int(line[t1+1:t2])
    return num_steps, conversion_window_limit, eval(line[t2+1:])

# 60\t[(1719535134.119179,(1,0)),(1719988603.504339,(1,0)),(1720155830.04705,(1,0))]
# Funnel is ordered, assume no time limit for now
# Optimizations - tuple into a bitmask
def parse_user_aggregation(line):
    num_steps, conversion_window_limit, timestamp_and_steps = parse_args(line)

    next_index = 1
    for timestamp, steps in timestamp_and_steps:
        if next_index in steps:
            next_index += 1
            if next_index > num_steps:
                break
    if next_index > 1:
        print(next_index - 2)

def parse_user_aggregatio1n(line):
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
        if next_index == num_steps + 1:
            print(line[t2+1:].replace("\n", ""))
        else:
            print("")

if __name__ == '__main__':
    for line in sys.stdin:
        parse_user_aggregation(line)
        #print("Value " + line, end='')
        sys.stdout.flush()
