# Maintaining workflow lockfiles

Read this before changing a workflow listed in `.github/workflows/actions.lock`, its action dependencies, or the lockfile itself.

The lockfile's `workflows` section lists the onboarded workflows.
Onboard another workflow in its own change, and add it to the Renovate exclusion in `.github/renovate.json5` in that change.

## Update and verify

Use the `gh-actions-lock` version pinned in `.github/workflows/ci-lint-workflows.yml`.

After changing an onboarded workflow's action references, regenerate and verify only that workflow.
Without a workflow path, `gh actions-lock` onboards every workflow.

```sh
gh actions-lock .github/workflows/<workflow>.yml
gh actions-lock --verify .github/workflows/<workflow>.yml
```

Commit the workflow and the generated lockfile together.

Keep the rule-specific `nosemgrep` annotation on each locked tag reference.
Semgrep's mutable-action-tag rule does not read `actions.lock`.

Review the generated diff:

- Confirm that changed commits match the intended dependency update, and investigate changed repository or owner IDs.
- Confirm that the run onboarded no other workflow and rewrote no shared action.

Never delete the lockfile to resolve an error.
Restore a valid copy and regenerate.
Do not use `--relock` or `--accept-moved` to silence a provenance error before you review the upstream change.

## Coverage boundaries

- The lockfile does not cover remote reusable-workflow calls at `jobs.<job_id>.uses`. Keep their inline SHA pins.
- `gh-actions-lock` does not follow local `./` actions. A migration to `$/` changes which commit supplies the action, so keep it out of routine lockfile maintenance.

See GitHub's [lockfile maintenance guide](https://docs.github.com/en/actions/how-tos/secure-your-work/lock-workflow-dependencies) and the [gh-actions-lock limitations](https://github.com/github/gh-actions-lock#limitations).
