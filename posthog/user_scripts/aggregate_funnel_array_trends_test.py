#!/usr/bin/python3

import sys
import json

if __name__ == "__main__":
    for line in sys.stdin:
        try:
            print(json.dumps({"result": line}))  # noqa: T201
        except Exception as e:
            print(json.dumps({"result": json.dumps(str(e))}), end="\n")  # noqa: T201
        sys.stdout.flush()
