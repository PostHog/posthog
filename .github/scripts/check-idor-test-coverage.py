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
import json
from pathlib import Path

SNAPSHOT_PATH = Path(__file__).resolve().parent.parent.parent / "posthog" / "test" / "idor" / "_coverage_snapshot.json"


def setup_django() -> None:
    repo_root = str(Path(__file__).resolve().parent.parent.parent)
    sys.path.insert(0, repo_root)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    import django

    django.setup()


def _enumerate_pairs() -> tuple[set[str], set[str]]:
    """Enumerate all (viewset, FK field) and (viewset, action) pairs.

    Returns two sets of dotted-string keys. The caller compares them to
    the snapshot to detect new pairs that haven't been audited yet.
    """
    from posthog.test.idor.discovery import discover_idor_test_cases
    from posthog.test.idor.fk_discovery import discover_action_serializers, discover_writable_tenant_fks

    fk_pairs: set[str] = set()
    action_pairs: set[str] = set()
    for case in discover_idor_test_cases():
        serializer_cls = getattr(case.viewset_cls, "serializer_class", None)
        if serializer_cls is not None:
            for fk in discover_writable_tenant_fks(serializer_cls):
                key = f"{case.name}.{'.'.join((*fk.nested_path, fk.serializer_field_name))}.{fk.target_model.__name__}"
                fk_pairs.add(key)
        for action in discover_action_serializers(case.viewset_cls):
            action_pairs.add(f"{case.name}.{action.method_name}")
    return fk_pairs, action_pairs


def _load_snapshot() -> dict[str, list[str]]:
    if not SNAPSHOT_PATH.exists():
        return {"fk_pairs": [], "action_pairs": []}
    with SNAPSHOT_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_snapshot(fk_pairs: set[str], action_pairs: set[str]) -> None:
    payload = {
        "fk_pairs": sorted(fk_pairs),
        "action_pairs": sorted(action_pairs),
    }
    with SNAPSHOT_PATH.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")


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


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    update_snapshot = "--update-snapshot" in args

    setup_django()

    from posthog.api import router
    from posthog.api.routing import TeamAndOrgViewSetMixin
    from posthog.test.idor.discovery import discover_idor_test_cases
    from posthog.test.idor.fk_discovery import discover_writable_tenant_fks
    from posthog.test.idor.skip_list import IDOR_FK_PATCH_SKIP_LIST, IDOR_TEST_SKIP_LIST

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

    # 4. Phase 5a — every (auto-tested viewset × writable tenant-FK field) pair
    #    must either be covered by `test_cross_tenant_fk_in_patch` or be in
    #    IDOR_FK_PATCH_SKIP_LIST (with the entire viewset skipped). The
    #    parametric test enumerates the same product, so this exists primarily
    #    to surface counts and to keep IDOR_FK_PATCH_SKIP_LIST entries honest.
    fk_total = 0
    fk_already_scoped = 0
    fk_unscoped = 0
    fk_implicit = 0
    fk_many = 0
    fk_create_only = 0
    fk_pairs_by_viewset: dict[str, list[str]] = {}
    for case in discover_idor_test_cases():
        if case.name in IDOR_FK_PATCH_SKIP_LIST:
            continue
        serializer_cls = getattr(case.viewset_cls, "serializer_class", None)
        if serializer_cls is None:
            continue
        for fk in discover_writable_tenant_fks(serializer_cls):
            fk_total += 1
            if fk.is_already_scoped:
                fk_already_scoped += 1
            else:
                fk_unscoped += 1
            if fk.is_implicit:
                fk_implicit += 1
            if fk.is_many:
                fk_many += 1
            if fk.is_create_only:
                fk_create_only += 1
            label = ".".join((*fk.nested_path, fk.serializer_field_name))
            fk_pairs_by_viewset.setdefault(case.name, []).append(label)

    fk_skips = set(IDOR_FK_PATCH_SKIP_LIST.keys())
    stale_fk_skips = sorted(s for s in fk_skips if s not in {c.name for c in discover_idor_test_cases()})
    if stale_fk_skips:
        print()
        print("ERROR: IDOR_FK_PATCH_SKIP_LIST contains entries that no longer match any auto-tested viewset:")
        for name in stale_fk_skips:
            print(f"  - {name}")
        print("Remove stale entries from posthog/test/idor/skip_list.py.")
        return 1

    print()
    print(f"[idor-fk-coverage]   writable tenant-FK fields covered: {fk_total}")
    print(f"[idor-fk-coverage]     - already-scoped (defense in depth): {fk_already_scoped}")
    print(f"[idor-fk-coverage]     - implicit `<thing>_id` pattern:    {fk_implicit}")
    print(f"[idor-fk-coverage]     - many=True (M2M):                  {fk_many}")
    print(f"[idor-fk-coverage]     - create-only (read_only_fields):   {fk_create_only}")
    print(f"[idor-fk-coverage]     - unscoped (primary IDOR risk):     {fk_unscoped}")
    print(f"[idor-fk-coverage]   viewsets explicitly skipped:        {len(fk_skips)}")
    print(f"[idor-fk-coverage]   viewsets with at least one FK pair: {len(fk_pairs_by_viewset)}")

    # 5. Snapshot enforcement — every (viewset, FK) and (viewset, action)
    #    pair must be in `_coverage_snapshot.json`. New pairs fail the gate
    #    so a freshly-added action or FK can't slip past the parametric
    #    sweep without an explicit acknowledgement. Run with
    #    `--update-snapshot` to refresh the file after auditing.
    fk_pairs, action_pairs = _enumerate_pairs()
    if update_snapshot:
        _write_snapshot(fk_pairs, action_pairs)
        print()
        print(f"[idor-snapshot]      wrote {len(fk_pairs)} FK + {len(action_pairs)} action pairs to {SNAPSHOT_PATH}")
    else:
        snapshot = _load_snapshot()
        snapshot_fk = set(snapshot.get("fk_pairs", []))
        snapshot_action = set(snapshot.get("action_pairs", []))
        new_fk = sorted(fk_pairs - snapshot_fk)
        new_action = sorted(action_pairs - snapshot_action)
        if new_fk or new_action:
            print()
            print("ERROR: new (viewset, FK) or (viewset, action) pairs not in coverage snapshot:")
            for entry in new_fk:
                print(f"  + FK    {entry}")
            for entry in new_action:
                print(f"  + ACT   {entry}")
            print()
            print("Each entry must either be exercised by the parametric sweep or added")
            print("to IDOR_FK_PATCH_SKIP_LIST / IDOR_FK_POST_SKIP_LIST / IDOR_ACTION_SKIP_LIST")
            print("with a documented reason. Once audited, refresh the snapshot:")
            print()
            print("  python .github/scripts/check-idor-test-coverage.py --update-snapshot")
            return 1
        stale_fk = sorted(snapshot_fk - fk_pairs)
        stale_action = sorted(snapshot_action - action_pairs)
        if stale_fk or stale_action:
            print()
            print("WARNING: snapshot lists pairs that no longer exist (refresh with --update-snapshot):")
            for entry in stale_fk[:10]:
                print(f"  - FK    {entry}")
            for entry in stale_action[:10]:
                print(f"  - ACT   {entry}")

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
