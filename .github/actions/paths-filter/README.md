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

## `since-last-push`: filtering on the pushed commits only

By default a `pull_request` run filters on everything the pull request changes,
so a follow-up push that touches only docs still re-runs every suite the earlier commits matched.
`since-last-push: true` narrows detection to the commits the triggering push added:

```yaml
- uses: ./.github/actions/paths-filter
  with:
    token: ${{ steps.app-token.outputs.token || github.token }}
    # Trunk's merge queue is the merge gate, so its runs always see the full diff.
    since-last-push: ${{ !startsWith(github.head_ref, 'trunk-merge/') }}
    filters: |
      frontend:
        - 'frontend/**'
```

It reads `before`/`after` off the `synchronize` payload and asks the compare API for `before...after`.
Three dots means the comparison starts from `merge-base(before, after)`,
so an appended push reports exactly its own commits,
while a force-push or rebase widens to the whole branch delta instead of reporting a wrong one.

The full pull request diff is used instead whenever the push delta isn't available or isn't trustworthy:
any event other than `synchronize` (including `opened` and `ready_for_review`),
a missing or null `before`/`after`,
no `token`,
an API error,
or a comparison at the API's 300-file cap, where the file list may be truncated.
Every fallback reports more changes than the push delta would, never fewer.

**Know the trade-off before enabling this.**
Pull request runs cancel in progress on a new push.
If push A touches Rust and push B touches only docs,
A's Rust job can be cancelled while B's run filters it out,
so nothing tests A on this pull request.
What makes that survivable here is that Trunk's merge queue re-runs CI on a fresh `trunk-merge/**` pull request,
whose full diff against master is the actual merge gate.
The cost is that the breakage surfaces in the queue rather than on the pull request.
Enable this on suites where that trade is worth the runner time, and keep the merge queue on the full diff.

Detection is per invocation,
so a workflow can gate cheap jobs on the push delta
while a second step keeps the whole-pull-request `*_files` lists that test selection and lint scoping need.

## Rebuilding after source changes

The action runs the committed `dist/index.js` bundle. After editing anything under `src/`,
regenerate it and re-run the tests:

```bash
npm ci
npm test
npx ncc build src/main.ts -o dist
```

Commit the updated `dist/index.js` alongside the source change.
