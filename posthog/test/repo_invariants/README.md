# Repo invariants

Tests here inspect the whole repository through the import graph after `django.setup()`, `apps.get_models()`, signal receiver registries, and AST scans against a baseline.
Any file can break them, so selecting tests by changed paths cannot reliably include them.

The `repo-checks` job in `.depot/workflows/ci-backend.yml` therefore runs this directory on every PR that touches backend code, including products-only diffs and drafts.
That job has no Postgres or ClickHouse, and the Core Django shards skip this directory.

A test that compares a committed file with the code that generates it, or a registry with what is defined, also goes here.
Such a test gives the same result every time for the same code, so when it fails on every pull request in the merge queue, master is broken.
The Django and product jobs pass their failures through a Trunk quarantine gate, and Trunk quarantines a test that fails often in the merge queue.
The `repo-checks` job has no such gate, so a failure here always fails the pull request.

Do not use database or ClickHouse fixtures here.
Put other tests that inspect a bounded set of files next to the code they cover.
Regenerate baselines with the commands the failing tests print.
