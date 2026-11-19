# paths-filter (vendored)

A vendored fork of [`dorny/paths-filter`](https://github.com/dorny/paths-filter) `v4.0.1`
(commit `fbd0ab8f3e69293af611ebaee6363fc25e6d187d`, MIT — see [LICENSE](./LICENSE)).

Use it exactly like the upstream action, but reference it by path instead of by tag:

```yaml
- uses: ./.github/actions/paths-filter
  id: filter
  with:
    filters: |
      backend:
        - 'posthog/**'
```

## Why we forked

Upstream's `predicate-quantifier` is global per filter and can't express a common need:
**"run on everything in folder X, except `*.md`"** — i.e. `(match A OR B) AND (NOT *.md)`.

- With the default `some` (OR) quantifier, `!` patterns are silently ignored: any non-`.md`
  file still matches the positive glob, so the filter passes.
- With `every` (AND), the `!` excludes work, but the positive patterns can no longer be
  OR-ed together — a file must match _all_ of them.

## How matching works

This fork drops upstream's `some`/`every` quantifiers and always uses include/exclude
matching (there is no `predicate-quantifier` input):

- Positive patterns are **includes**, OR-ed together.
- Every `!`-prefixed pattern is an **exclude** that vetoes a match.
- A file matches when it matches at least one include (or there are no includes) **and**
  matches no exclude.

```yaml
- uses: ./.github/actions/paths-filter
  with:
    filters: |
      backend:
        - 'posthog/**'
        - 'products/**/backend/**'
        - '!**/*.md'
```

For a filter with only positive patterns this behaves exactly like upstream's default
`some` — so plain filters are unaffected.

### Limitation: excludes must be top-level entries

An exclude is only recognised when the `!` pattern is its own entry in the filter list.
A `!` pattern nested inside a change-status array is rejected with an error rather than
silently falling through to picomatch's raw negation (which would match every file outside
the pattern) — that fallthrough is the upstream footgun this fork exists to avoid. Write
excludes as separate entries:

```yaml
# do this
changed:
  - added|modified: 'src/**'
  - '!src/vendor/**'
# not this — throws "'!' patterns are not supported inside a change-status array"
changed:
  - added|modified: ['src/**', '!src/vendor/**']
```

## Reusing an earlier passing result (opt-in)

A pull request's filters answer for the whole pull request, so a suite that ran on the first push runs again on every later push, even one that touches none of its files.
Set `reuse-checks` and `reuse-proof-checks` to stop that: when a push changes no file the scoped filters match since the last head where the suite really ran and passed, the action reports those filters as unchanged.
The jobs they gate are skipped, the gate reads the skips as a pass, and the earlier result stands.

```yaml
- uses: ./.github/actions/paths-filter
  id: filter
  with:
    reuse-checks: Frontend Tests Pass
    reuse-proof-checks: Frontend formatting
    reuse-filters: |
      frontend
    reuse-blocking-labels: |
      run-ci-frontend
      ci-no-reuse
    reuse-disabled: ${{ vars.DISABLE_CI_REUSE }}
    filters: |
      frontend:
        - 'frontend/**'
```

| Input                   | Meaning                                                                                                                                       |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `reuse-checks`          | Check run names, one per line. Each must have concluded `success` or `skipped` on every head the action reads. Empty turns reuse off.         |
| `reuse-proof-checks`    | Check run names of jobs that run only when the suite really runs. A head counts as tested when one of them concluded `success`. Required.     |
| `reuse-check-apps`      | GitHub App slugs whose check runs count for the two inputs above. Runs from any other App are ignored. Defaults to `github-actions`.          |
| `reuse-filter-source`   | The file that defines the filters. Defaults to the `filters` file, then to the workflow file. Set it where `GITHUB_WORKFLOW_REF` is not set.  |
| `reuse-filters`         | The filters reuse applies to, one per line. Defaults to every filter in the step.                                                             |
| `reuse-blocking-labels` | Labels that turn reuse off, for the labels that force a fuller run.                                                                           |
| `reuse-disabled`        | `'true'` turns reuse off. Wire it to a repository variable to have a kill switch. Depot CI reads its own variables, so set it in both stores. |

The outputs `reused` and `reused_from` say whether a result was reused and from which commit.

The action reuses a result only when every one of these holds, and runs the suite otherwise:

- The event is a push to a same-repository pull request (`synchronize`) that is not a merge queue branch, and this is the run's first attempt.
  Re-running the workflow always runs the suite.
- The action finds the proven head: it walks back from the previous head through the pull request's commits, at most 20, to the newest head where a proof check concluded `success`.
  Every `reuse-checks` check passed on each head it reads, and a head where any of them failed, was cancelled or is still running stops the walk.
  A gate that passed because the suite was skipped (a reused result, a superseded run, a bot push) is never the proven head.
- The files the scoped filters match, plus the file that defines the filters, are the same set, with the same change status and the same content, on the previous head, the proven head and this one.
  The comparison uses each file's blob SHA from the API, so a formatting-only edit counts as a change.
  Each file also keeps the same Git mode on the proven head and this one, so a lost executable bit counts as a change.
- Every check run the action reads comes from an App in `reuse-check-apps`.
- No other pull request, open or merged, contains the proven head, because check runs on a shared commit can come from a pull request with a different base.
- The proven run started less than 24 hours ago.
  Its start is the creation time of the earliest check suite among the check runs it reads, which is no later than the moment its filters were evaluated.
- On a pull request that is ready for review, the proven run started after it was marked ready, because a draft can run a narrower suite.
- The pull request's base was not changed or force-pushed after the proven run started, and no commit on the base branch has changed the file that defines the filters since then.
- Neither file list is truncated (3,000 files for this head, 300 for the others), and every API call succeeded within 20 seconds.

Scope decides how often this fires.
All scoped filters are compared as one set and cleared together, so one broad filter in the scope (`'**'`) makes every push count as a change.
Leave such a filter out of `reuse-filters`; it keeps answering from the real file list.
The scoped filters must match every file the suite reads, including the local actions its jobs run and any file a selector reads from the diff.
A file the suite reads outside them can change without stopping a reuse.

The comparison covers the files the pull request changes, not the base branch.
Every reused result keeps the master side of the proven run, which can be up to 24 hours old.
A rebase that leaves the scoped files alone counts the same way.
The merge queue run never reuses a result, so it still tests the real merge.

Name every check whose failure should stop a reuse.
A job that the scoped filters gate but no named check covers shows as skipped after a reuse, even when it failed on the previous head.

Set `PATHS_FILTER_REUSE_POSTHOG_TOKEN` on the step to record each decision as a `posthog-ci-reuse-decision` event, with a closed `reason` and a free-text `detail`.

## Shadow comparison (opt-in)

Set `PATHS_FILTER_SHADOW_POSTHOG_TOKEN` on a step to have that run compare the API's
changed-file list against the same list derived from the pull request's merge commit,
and send the verdict to PostHog. The comparison never changes what the filter answers.

```yaml
- uses: ./.github/actions/paths-filter
  env:
    PATHS_FILTER_SHADOW_POSTHOG_TOKEN: ${{ secrets.POSTHOG_DEVEX_PROJECT_API_TOKEN }}
```

Without the variable the action does no extra work. Set it in one workflow that runs on
every pull request; that keeps the merge-ref fetch off the critical path of the other
gating jobs. This is temporary, and goes away with the decision it exists to inform.

The event carries the differing paths and, in `selection_changed` and `keys_lost`, which
filter keys answer differently on the two lists. The keys are what gate a job, so they are
what the decision reads; the paths are there to explain a flip.

## Rebuilding after source changes

The action runs the committed `dist/index.js` bundle. After editing anything under `src/`,
regenerate it and re-run the tests:

```bash
npm ci
npm test
npx ncc build src/main.ts -o dist
```

Commit the updated `dist/index.js` alongside the source change.
