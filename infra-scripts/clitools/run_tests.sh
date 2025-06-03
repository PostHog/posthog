#!/bin/bash

# Run the tests
# Get directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"
python3 -m unittest test_toolbox.py -v