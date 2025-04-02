#!/usr/bin/env python3
"""
This script is used to copy the executable to a in-memory file descriptor before executing it.
This allows us to deploy new copies of the executable without always creating a new version.
The new version will get picked up by clickhouse the next time the function is reloaded.
The lifetime option in user_defined_function.xml file controls how often clickhouse reloads the function.

Usage:
    ./mem_exec.py <path_to_executable> [args...]
"""

import os
import sys

# Check if an executable path is provided
if len(sys.argv) < 2:
    print(f"Usage: {sys.argv[0]} <executable>")  # noqa: T201
    sys.exit(1)

executable = sys.argv[1]

try:
    with open(executable, "rb") as src_file:
        # Create an anonymous in-memory file descriptor
        mem_fd = os.memfd_create("my_executable", 0)

        # Copy the executable into memory
        while True:
            chunk = src_file.read(4096)
            if not chunk:
                break
            os.write(mem_fd, chunk)

    fd_path = f"/proc/self/fd/{mem_fd}"
    os.execv(fd_path, [executable] + sys.argv[2:])
except Exception as e:
    print(f"Error: {e}")  # noqa: T201
    sys.exit(1)
finally:
    # Ensure the file descriptor is closed if something fails before execv
    try:
        os.close(mem_fd)
    except:
        pass
