#!/usr/bin/python3

import os
import sys
import json

if __name__ == "__main__":
    # ClickHouse starts this script with copies of its open client connections. A retained copy keeps a connection
    # open after the server closes it, so the client's next request on that connection never gets a response.
    os.closerange(3, os.sysconf("SC_OPEN_MAX"))
    for line in sys.stdin:
        try:
            print(json.dumps({"result": line}))  # noqa: T201
        except Exception as e:
            print(json.dumps({"result": json.dumps(str(e))}), end="\n")  # noqa: T201
        sys.stdout.flush()
