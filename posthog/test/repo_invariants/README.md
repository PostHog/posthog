# Repo invariants

Tests here take the whole repo as input: the import graph after `django.setup()`,
`apps.get_models()`, signal receiver registries, repo-wide AST scans against a
baseline. Any file anywhere can break them, and diff-based test selection has no
way to pick them from a diff.

So CI runs this directory unconditionally on every backend-touching PR, including
products-only diffs and drafts, as a step of the `repo-checks` job in
`.github/workflows/ci-backend.yml`. There is no Postgres or ClickHouse in that
job, and the Core Django shards skip this directory.

Rules: no database or ClickHouse fixtures. A test whose input is a bounded set of
files belongs next to the code it covers, not here. Regenerate baselines with the
commands the tests print when they fail.
