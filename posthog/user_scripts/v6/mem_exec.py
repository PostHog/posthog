#!/usr/bin/env python3
import os
import sys

# Check if an executable path is provided
if len(sys.argv) < 2:
    print(f"Usage: {sys.argv[0]} <executable>")  # noqa: T201
    sys.exit(1)

executable = sys.argv[1]

# Open the original executable
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

        # Prepare the /proc/self/fd path for execution
        fd_path = f"/proc/self/fd/{mem_fd}"

        # Execute the in-memory file
        os.execv(fd_path, [executable] + sys.argv[2:])
except FileNotFoundError:
    print(f"Error: Could not find executable '{executable}'")  # noqa: T201
    sys.exit(1)
except PermissionError:
    print("Error: Permission denied")  # noqa: T201
    sys.exit(1)
except Exception as e:
    print(f"Error: {e}")  # noqa: T201
    sys.exit(1)
finally:
    # Ensure the file descriptor is closed if something fails before execv
    try:
        os.close(mem_fd)
    except:
        pass
