# Imported before anything else to overwrite env vars!

import os
import sys

"""
There are several options:
1) running in pycharm
        second argument is "test"
2) running pytest at the CLI
        first argument is the path to pytest and ends pytest
3) running pytest using the script at /bin/tests
        first argument is the path to pytest and ends pytest
4) running in some other context (e.g. in prod)
        first argument does not end pytest
        second argument is not test

Arguments to the application will be slightly different in each case

So, in order to set test variables we need to look in slightly different places

The /bin/tests file also runs mypy to do type checking. This needs DEBUG=1 set too

Running pytest directly does not always load django settings but sometimes needs these environment variables.
We use pytest-env to let us set environment variables from the closest pytest.ini

We can't rely only on pytest.ini as some tests evaluate this file before its environment variables have been read
"""
runner = sys.argv[0] if len(sys.argv) >= 1 else None

cmd = None
if runner:
    cmd = sys.argv[1] if len(sys.argv) >= 2 else None

    if cmd == "test" or runner.endswith("pytest") or runner.endswith("mypy") or "/mypy/" in runner:
        print("Running in test mode. Setting DEBUG and TEST environment variables.")  # noqa: T201
        os.environ["DEBUG"] = "1"
        os.environ["TEST"] = "1"
