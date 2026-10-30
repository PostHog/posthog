# Maintaining workflow lockfiles

Read this before adding a workflow, changing any `uses:`, or editing `.github/workflows/actions.lock`.

Every workflow under `.github/workflows/` is onboarded.
`Lint workflows` runs `gh actions-lock --verify`, which fails when a workflow or `uses:` has no lockfile entry.
Action bumps are manual, and Renovate does not bump actions.

## Update and verify

Use the `gh-actions-lock` version pinned in `.github/workflows/ci-lint-workflows.yml`.

After adding a workflow or changing a `uses:`, regenerate and verify:

```sh
gh actions-lock --migrate-local-actions
gh actions-lock --verify
```

Commit the workflows and the generated lockfile together.

Reference in-repo composites as `$/.github/actions/<name>`, which runs them at the workflow's own commit.
A `./` composite that uses a remote action fails the lockfile check, and `--migrate-local-actions` rewrites it to `$/`.
Depot CI workflows and actions under `.depot/` keep `./`, because the lockfile does not cover them.

The lockfile check replaces semgrep's mutable-action-tag rule under `.github/`, so `ci-security.yaml` excludes that rule.
`.semgrep/rules/security/github-actions-mutable-action-tag-depot.yaml` keeps SHA pins required under `.depot/`.
Depot mirrors under `.depot/actions/` keep SHA pins, so a mirror whose canonical action has a third-party `uses:` is listed in `DELTA_MIRRORS` in `depot_mirrors.py`.

Review the generated diff:

- Confirm that changed commits match the intended dependency update, and investigate changed repository or owner IDs.
- Confirm that the run rewrote no workflow you did not change.

Never delete the lockfile to resolve an error.
Restore a valid copy and regenerate.
Do not use `--relock` or `--accept-moved` to silence a provenance error before you review the upstream change.

## Coverage boundaries

- The lockfile does not cover remote reusable-workflow calls at `jobs.<job_id>.uses`. Keep their inline SHA pins.
- actionlint does not parse `$/` yet ([rhysd/actionlint#711](https://github.com/rhysd/actionlint/issues/711)), so `.github/actionlint.yaml` ignores that one error.

See GitHub's [lockfile maintenance guide](https://docs.github.com/en/actions/how-tos/secure-your-work/lock-workflow-dependencies) and the [gh-actions-lock limitations](https://github.com/github/gh-actions-lock#limitations).
