#!/usr/bin/env python3

"""Backward-compatible shim that re-exports DuckLake helpers from the Django package."""

from posthog.ducklake.common import *  # noqa: F401,F403
