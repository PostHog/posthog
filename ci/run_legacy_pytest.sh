#!/bin/bash
# Marker script for //ci:legacy_pytest target
#
# This script is NOT meant to be run directly by Bazel.
# It exists so that target-determinator can track when legacy code changes
# and signal to CI that the legacy pytest matrix should run.
#
# The actual pytest execution happens in .github/workflows/ci-backend.yml
# via the django matrix job.

echo "This is a marker target for target-determinator."
echo "Legacy pytest runs via the CI workflow, not via Bazel."
exit 0
