# Libs

Shared Python that more than one product imports, living in the monorepo venv.

A lib is a plain package at `posthog/libs/<name>/`, imported as `posthog.libs.<name>`.
There is no packaging step: no `pyproject.toml`, no uv workspace member, nothing to install.

Each lib is three things at once:

- A Python package: `posthog/libs/<name>/__init__.py`, its modules, and its tests.
- A tach node: `[[modules]] path = "posthog.libs.<name>"` with `depends_on = []` and an interfaces block, so it stays a leaf and only its declared surface is importable.
  Every consumer adds `"posthog.libs.<name>"` to its own `depends_on`; `tach check` fails on an undeclared import.
- A turbo workspace package: `posthog/libs/<name>/package.json` named `@posthog/lib-<name>` with a `backend:test` script, plus a `turbo.json` whose inputs cover its sources.
  Turbo runs the script from the lib's own directory, so it points back at the repo root: `pytest -c ../../../pytest.ini --rootdir ../../.. --durations-path ../../../.test_durations tests -v --tb=short` (the durations path keeps master's timing collection in the root file).
  CI runs the lib's own tests and the tests of the products that declare it, and skips the Django suite unless `posthog` or `ee` declares it too.

Keep folder names `under_score` cased, because dashes break Python imports.

## When a lib is the right home

Reach for `posthog/libs/<name>/` when shared Python is imported by more than one product and needs neither Django nor anything else from `posthog/`.

Somewhere else if:

- One product owns it.
  Put it under `products/<product>/`.
  It is not shared until a second product actually imports it.
- It needs Django or the rest of core, or core imports it.
  Put it in `posthog/<mechanism>/` outside `libs/`.
  Either way a change re-runs the full Django suite, so a lib buys nothing.
- A consumer must install it outside the monorepo venv, such as a bare-python CI step, a sandbox, or another repo.
  That is a distribution, so it belongs in `packages/<name>/` with its own `pyproject.toml`.

Full rules, including how this sits next to `common/`, `packages/`, `services/`, and `tools/`, are in [docs/internal/monorepo-layout.md](../../docs/internal/monorepo-layout.md).
