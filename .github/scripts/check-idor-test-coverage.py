#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
CI script: verify every tenant-scoped DRF viewset with a detail endpoint
is either auto-IDOR-tested by `posthog/test/test_idor_coverage.py` or
explicitly listed in `posthog/test/idor/skip_list.py`.

This complements `check-idor-model-coverage.py` (which gates the semgrep
rule model list) by ensuring viewset-level IDOR test coverage grows as
new tenant-scoped viewsets are added.

Usage:
    python .github/scripts/check-idor-test-coverage.py

Exit codes:
    0 - All tenant-scoped detail viewsets are covered (auto-tested or skipped)
    1 - Found uncovered viewsets (ERROR)
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


def setup_django() -> None:
    repo_root = str(Path(__file__).resolve().parent.parent.parent)
    sys.path.insert(0, repo_root)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    import django

    django.setup()


_NAMED_GROUP_RE = re.compile(r"\(\?P<([^>]+)>")


def _has_detail_endpoint(cls: type) -> bool:
    """Return True if this viewset has at least one URL with a non-format, non-parent-lookup named group at the end."""
    from posthog.api import router

    for url_pattern in router.urls:
        callback = getattr(url_pattern, "callback", None)
        pattern_cls = getattr(callback, "cls", None)
        if pattern_cls is not cls:
            continue
        kwargs = _NAMED_GROUP_RE.findall(str(url_pattern.pattern))
        if not kwargs:
            continue
        last = kwargs[-1]
        if last == "format":
            continue
        if last.startswith("parent_lookup_"):
            continue
        return True
    return False


def main() -> int:
    setup_django()

    from posthog.api import router
    from posthog.api.routing import TeamAndOrgViewSetMixin
    from posthog.test.idor.discovery import discover_idor_test_cases
    from posthog.test.idor.skip_list import IDOR_TEST_SKIP_LIST

    # 1. Enumerate every unique tenant-scoped viewset that has a detail endpoint
    #    (i.e. a URL matching something other than `format` / `parent_lookup_*` as its final kwarg).
    all_tenant_scoped: dict[str, type] = {}
    for url_pattern in router.urls:
        callback = getattr(url_pattern, "callback", None)
        cls = getattr(callback, "cls", None)
        if cls is None:
            continue
        if not issubclass(cls, TeamAndOrgViewSetMixin):
            continue
        if cls.__name__ in all_tenant_scoped:
            continue  # already seen via another URL registration
        if not _has_detail_endpoint(cls):
            continue
        all_tenant_scoped[cls.__name__] = cls

    # 2. What's covered?
    auto_tested = {case.name for case in discover_idor_test_cases()}
    skipped = set(IDOR_TEST_SKIP_LIST.keys())
    covered = auto_tested | skipped

    # 3. What's not covered?
    uncovered = sorted(n for n in all_tenant_scoped if n not in covered)

    print(f"[idor-test-coverage] total tenant-scoped detail viewsets: {len(all_tenant_scoped)}")
    print(f"[idor-test-coverage] auto-tested:                        {len(auto_tested)}")
    print(f"[idor-test-coverage] explicitly skipped:                 {len(skipped)}")
    print(f"[idor-test-coverage] uncovered:                          {len(uncovered)}")

    # Sanity check: every skip-list entry should name a real viewset that
    # actually exists. Stale entries mask future IDORs.
    stale_skips = sorted(s for s in skipped if s not in all_tenant_scoped)
    if stale_skips:
        print()
        print("ERROR: skip_list contains entries that no longer match any tenant-scoped viewset:")
        for name in stale_skips:
            print(f"  - {name}")
        print("Remove stale entries from posthog/test/idor/skip_list.py.")
        return 1

    if uncovered:
        print()
        print("ERROR: these tenant-scoped viewsets with detail endpoints are NOT IDOR-covered:")
        for name in uncovered:
            cls = all_tenant_scoped[name]
            print(f"  - {name} (model={_model_name(cls)}, lookup_field={getattr(cls, 'lookup_field', 'pk')})")
        print()
        print("For each, do one of:")
        print(
            "  1. Add an entry to the fixture registry in posthog/test/idor/fixtures.py (if the "
            "model has required FKs or custom validation)."
        )
        print(
            "  2. Add an entry to IDOR_TEST_SKIP_LIST in posthog/test/idor/skip_list.py with a "
            "documented category + reason (e.g., intentionally cross-team, custom lookup field, "
            "or latent bug tracked elsewhere)."
        )
        print(
            "  3. Verify the URL regex parses — `posthog/test/idor/url_structure.py::parse_url_pattern` "
            "must return a URLStructure for the viewset's detail URL."
        )
        return 1

    print()
    print("OK — all tenant-scoped detail viewsets are IDOR-covered.")
    return 0


def _model_name(cls: type) -> str:
    qs = getattr(cls, "queryset", None)
    if qs is not None:
        model = getattr(qs, "model", None)
        if model is not None:
            return model.__name__
    serializer_cls = getattr(cls, "serializer_class", None)
    if serializer_cls is not None:
        meta = getattr(serializer_cls, "Meta", None)
        if meta is not None:
            model = getattr(meta, "model", None)
            if model is not None:
                return model.__name__
    return "?"


if __name__ == "__main__":
    sys.exit(main())
