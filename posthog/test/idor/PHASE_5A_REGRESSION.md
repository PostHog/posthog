# Phase 5a regression verification

This file documents the verification methodology for Phase 5a
(`test_cross_tenant_fk_in_patch`) against three previously-shipped IDOR
fixes. The goal: prove that the framework, when run against the
**pre-fix** state of each branch, raises the very vulnerability the fix
addressed.

## Method

For each fixed branch:

1. Find the merge base with `master`.
2. Check out the commit immediately _before_ the fix.
3. Cherry-pick (or rebase) the Phase 5a commits on top.
4. Run `hogli test posthog/test/test_idor_coverage.py::TestAutomatedIDORCoverage::test_cross_tenant_fk_in_patch_*<viewset>*<field>`.
5. Expect: the test fails with the IDOR assertion message.

Snippet (rerun locally; not committed):

```sh
for branch in tom/fix tom/refactor-batch-exports tom/check-owner; do
  echo "=== $branch (pre-fix) ==="
  git checkout "${branch}^"
  git cherry-pick tom/auto-idor-check~6..tom/auto-idor-check  # Phase 5a commits
  hogli test posthog/test/test_idor_coverage.py::TestAutomatedIDORCoverage \
    -k test_cross_tenant_fk_in_patch
done
```

## Branches in scope

| Branch                       | Class of IDOR                                         | Expected pre-fix failure                                                                                                  |
| ---------------------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `tom/fix`                    | `DatasetItem.dataset` writable across teams via PATCH | `DatasetItemViewSet__dataset`                                                                                             |
| `tom/refactor-batch-exports` | `BatchExportDestination.integration` cross-team       | `BatchExportViewSet__destination__integration` (and `BatchExportOrganizationViewSet`)                                     |
| `tom/check-owner`            | EventDefinition owner FK pointing at user outside org | covered if `EventDefinition` viewset emits an OrganizationMembership FK; otherwise covered by FK PATCH on the owner field |

## Out of scope

- **`tom/dashboard-template`**: the IDOR was a string-by-name lookup
  (`name=` rather than `id=`), so Phase 5a's writable-FK detection does
  not apply. Tracked as Phase 5d follow-up — best handled by a new
  semgrep rule or manual taint analysis. Confirming the test does _not_
  flag this case is a negative result, not a bug.

## Result template

When you run the verification, paste the actual output here:

```text
=== tom/fix (pre-fix) ===
FAIL test_cross_tenant_fk_in_patch_<n>_DatasetItemViewSet__dataset
  IDOR: PATCH /api/environments/<id>/dataset_items/<pk>/ bound attacker's
        DatasetItem.dataset to victim's Dataset(pk=<x>)

=== tom/refactor-batch-exports (pre-fix) ===
FAIL test_cross_tenant_fk_in_patch_<n>_BatchExportViewSet__destination__integration
  ...

=== tom/check-owner (pre-fix) ===
...
```

If a branch's pre-fix code does **not** trigger a Phase 5a failure but
the IDOR is real, the framework needs extension (likely Phase 5b/5c/5d).
File a follow-up rather than tweaking the test to pass — silently
patching the canary defeats the point.
