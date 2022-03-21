#!/bin/bash

set -ex
python3 -m pip install pyyaml
echo
python3 docker-compose-config.py
