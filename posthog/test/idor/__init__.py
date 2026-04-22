"""
IDOR (cross-tenant access) test infrastructure.

This package provides automated cross-team IDOR coverage for every
tenant-scoped DRF viewset registered under `/api/`. The system has four
layers:

  - `url_structure` — parses DRF URL regexes into structured
    `URLStructure` objects (root parent type + intermediate parents +
    resource prefix + pk kwarg).

  - `discovery` — walks `posthog.api.router.urls`, classifies each
    viewset, and emits `IDORTestCase` entries for tenant-scoped viewsets
    with detail endpoints.

  - `factory` — `build_minimal_instance` uses Django `_meta`
    introspection to auto-create minimal model instances scoped to a
    given team. Caller can supply overrides for required FKs.

  - `mixin` — `IDORTestMixin` sets up a second `victim` org/team/user
    alongside the default `APIBaseTest` fixtures and provides
    `assertCrossTeamDenied` and related helpers.

See `posthog/test/test_idor_coverage.py` for the parametrized test that
consumes these components and verifies every tenant-scoped viewset
prevents cross-team access to detail endpoints.
"""

from posthog.test.idor.discovery import IDORTestCase, discover_idor_test_cases
from posthog.test.idor.factory import build_minimal_instance
from posthog.test.idor.mixin import IDORTestMixin
from posthog.test.idor.url_structure import URLStructure, parse_url_pattern

__all__ = [
    "IDORTestCase",
    "IDORTestMixin",
    "URLStructure",
    "build_minimal_instance",
    "discover_idor_test_cases",
    "parse_url_pattern",
]
