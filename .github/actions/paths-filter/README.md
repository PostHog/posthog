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

## Rebuilding after source changes

The action runs the committed `dist/index.js` bundle. After editing anything under `src/`,
regenerate it and re-run the tests:

```bash
npm ci
npm test
npx ncc build src/main.ts -o dist
```

Commit the updated `dist/index.js` alongside the source change.
