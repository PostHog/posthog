#!/usr/bin/python3
import sys
import json
import traceback

if __name__ == "__main__":
    for line in sys.stdin:
        try:
            # calculate_funnel_from_user_events(*parse_args(line))
            print(json.dumps({"result": line}))  # noqa: T201
        except Exception as e:
            print(json.dumps({"result": json.dumps(str(e) + traceback.format_exc())}), end="\n")  # noqa: T201
        sys.stdout.flush()
