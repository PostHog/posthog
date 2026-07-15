# Python type checking

PostHog runs both ty and mypy.
Both checks reject type errors in CI, while local hooks run narrower checks for faster feedback.

| Checker | Local hook                                                                                                             | CI role                                                               |
| ------- | ---------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| ty      | Runs on staged Python files through lint-staged and rejects the commit on errors                                       | Runs across the repository and blocks CI on errors                    |
| mypy    | Runs on eligible changed Python files through `hogli ci:preflight --strict` and rejects the push on errors or timeouts | Runs across the repository and remains the authoritative type checker |

`hogli ci:preflight` applies `[tool.mypy].exclude` before passing explicit paths to mypy, matching the files discovered by the full CI check.
If mypy is unavailable locally, preflight skips it and leaves CI as the gate.
ty does not run inside `hogli ci:preflight`; it runs through lint-staged before commit.

## Manual usage

```bash
uv run --no-sync ty check path/to/file.py
uv run --no-sync mypy -- path/to/file.py
hogli ci:preflight --strict
```

## Ty and mypy

**ty** provides fast feedback:

- Runs on staged Python files before commit
- Runs across the repository in CI
- Uses GitHub problem matcher to show warnings inline
- Has known limitations around Django and DRF metaprogramming

**mypy** remains the **authoritative type checker**:

- More mature and comprehensive
- Slower but thorough
- Uses its incremental cache to speed up repeat local checks
- Runs on changed files in strict preflight and across the repository in CI
- Blocks both strict preflight and CI on type errors

If a cached result looks stale, add `--no-incremental` before the `--` path separator in the printed mypy command to bypass cache reads.

## Configuration

ty rule categories where ty disagrees with mypy on idiomatic Django/DRF code are suppressed in `pyproject.toml` under `[tool.ty.rules]`.
This replaced the earlier `ty-baseline.txt` filter file (removed in #55368).
Add a new `<rule> = "ignore"` there if CI surfaces a spurious ty category.
