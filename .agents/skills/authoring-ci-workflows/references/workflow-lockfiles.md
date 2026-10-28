# Maintaining workflow lockfiles

Read this before changing a workflow listed in `.github/workflows/actions.lock`, its action dependencies, or the lockfile itself.

Use the lockfile's `workflows` section to determine which workflows are onboarded. Keep maintenance scoped to those workflows; onboarding another workflow is a separate change. Unonboarded workflows and native Depot CI keep inline SHA pins. Dependency-update automation is not required for this trial.

## Update and verify

Use the `gh-actions-lock` version pinned in `.github/workflows/ci-lint-workflows.yml`. After changing an onboarded workflow's action references, regenerate and verify only that workflow. For the trial:

```sh
gh actions-lock .github/workflows/ci-paths-filter.yml
gh actions-lock --verify .github/workflows/ci-paths-filter.yml
```

Include the workflow and generated lockfile changes in the same changeset. Run verification before reporting done, including for lockfile-only changes. `--verify-local` checks coverage offline; use `--verify` to check upstream provenance as well.

Preserve the trial's rule-specific `nosemgrep` annotations: Semgrep's mutable-action-tag rule does not read `actions.lock`. Keep these exceptions limited to references covered by the lockfile.

Review the generated diff:

- Confirm changed commits match the intended dependency update, and investigate changed repository or owner IDs.
- Confirm no unrelated workflows were onboarded or shared actions rewritten.
- Keep the trial workflow watching `actions.lock` so lockfile-only edits exercise it in CI.

Never hand-edit the lockfile or delete it to resolve an error. Restore a valid copy and regenerate. Do not run unscoped `gh actions-lock` during the trial, or use `--relock` or `--accept-moved` to silence a provenance error without reviewing the upstream change.

## Coverage boundaries

- Remote reusable-workflow calls at `jobs.<job_id>.uses` are not locked. Keep their inline SHA pins.
- Workspace-local `./` actions are not traversed. Migrating them to `$/` changes which commit supplies the action; do not include that migration in incidental lockfile maintenance.
- Container images and software downloaded by scripts need their own integrity checks.

See GitHub's [lockfile maintenance guide](https://docs.github.com/en/actions/how-tos/secure-your-work/lock-workflow-dependencies), [coverage limitations](https://github.com/github/gh-actions-lock#limitations), and [verification modes](https://github.com/github/gh-actions-lock#modes).
