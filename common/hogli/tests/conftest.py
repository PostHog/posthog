"""Shared test fixtures for hogli tests."""

import os

# Must be set before any Django-related imports during test collection
os.environ["DJANGO_SKIP_MIGRATIONS"] = "true"
