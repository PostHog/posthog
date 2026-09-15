# Backend CI on stacked pull requests

## Comparison policy

Backend CI selects tests for an ordinary pull request from the first parent of the workflow's merge commit to that merge commit.
Tests still execute the integrated tree, not the raw branch head.
For a native stack, this selects the current layer without counting newer trunk changes that the raw lower branch does not contain.

The workflows use Git's parent syntax and Turbo's `TURBO_SCM_BASE` and `TURBO_SCM_HEAD` settings.
The Python backend selector receives the same base through its existing `--base-ref` option.
The verdict job uses the same comparison when it must regenerate a missing selection artifact.

| Run                                  | Affectedness base                                                | Test tree             |
| ------------------------------------ | ---------------------------------------------------------------- | --------------------- |
| Ordinary PR, including a stack layer | `github.sha^1`                                                   | Workflow merge commit |
| Trunk queue PR (`trunk-merge/**`)    | Current `origin/<PR base>`                                       | Workflow merge commit |
| Non-PR run                           | Unchanged; legacy changes force full discovery when the job runs | Workflow commit       |

For example:

```text
Trunk:           O -- T
Lower branch:    O -- L
Current layer:        L -- H1 -- H2

Lower integration: I = merge(T, L)
Workflow merge:    M = merge(I, H2)

Ordinary PR comparison: I...M
Cumulative comparison:  T...M
Incorrect mixed range:  L...M  (also includes T's changes since O)
```

Do not replace every base reference with the first parent.
Schema-cache keys and migration checks have separate comparisons.
Selectors that compare the raw PR head against its raw base do not have this particular mismatch.

## Merge queue safety

This policy does not change queue triggers, path filters, lane scheduling, product dependency expansion, matrix construction, required checks, or quarantine policy.
The ordinary-PR selector remains disabled on `trunk-merge/**` runs.
Queue affectedness continues to use the fetched base branch, so it includes the candidate stack rather than only its last layer.

Disabling the ordinary-PR selector does **not** itself force every product into the queue matrix.
Existing discovery rules still decide which products and Django tests run.
Repository variables that disable tests, skipped dependencies, ruleset bypasses, and external Trunk configuration remain separate controls; this change does not strengthen them.

## Invalid merge checkouts

Before ordinary-PR discovery, the workflow checks that:

- `HEAD` matches `GITHUB_SHA`.
- The merge has exactly two parents.
- Its second parent matches the event's PR head SHA.
- Its first parent is available locally.

A failed check fails discovery, which fails `Django Tests Pass`.
It does not silently narrow coverage or fall back to a raw branch comparison.
A full test run against the wrong checkout would not validate the requested commit either.
Check the checkout ref and fetch depth before retrying a failed verification step.

The checks use commands already available on the runner.
An unrebased branch does not need a new helper, dependency, or generated file.

## Validation and rollout

Run `hogli test:workflows` for the topology and workflow-condition regressions.
The topology tests build local Git repositories with trunk drift and multiple commits in the current layer.
They exercise the configured comparisons, selector command, merge verification, and the required gate's failure handling.
They do not replace a live GitHub or Trunk run.

Also run `hogli lint:workflows`, actionlint, the Turbo discovery tests, and `hogli ci:preflight`.
Keep the canonical and optional Depot workflows aligned.

For rollout, compare an ordinary stacked PR's selected files and product matrix with its changed files, then observe the next normally authorized queue run.
Do not enqueue a probe solely to test this change.
If affectedness or merge verification behaves unexpectedly, revert the ordinary-PR base change and its verification step in both workflows; leave queue behavior unchanged.

## References

- [GitHub stacked pull requests](https://docs.github.com/en/pull-requests/reference/stacked-pull-requests)
- [GitHub pull request workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request)
- [Turbo affected queries](https://turborepo.dev/docs/reference/query)
- [Trunk stacked pull requests](https://docs.trunk.io/merge-queue/using-the-queue/stacked-pull-requests)
