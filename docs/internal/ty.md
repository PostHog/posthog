# Python type checking

PostHog runs both ty and mypy.
Both reject type errors in CI; locally, ty gates commits and mypy advises before push.

| Checker | Local hook                                                                                      | CI role                                                               |
| ------- | ----------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| ty      | Runs on staged Python files through lint-staged and rejects the commit on errors                | Runs across the repository and blocks CI on errors                    |
| mypy    | Runs repo-wide through `hogli ci:preflight` as a non-blocking advisory when Python files change | Runs across the repository and remains the authoritative type checker |

Preflight runs the identical repo-wide command CI runs (`mypy --cache-fine-grained .` with parallel workers), so its findings match CI instead of approximating it with changed-file lists, which follow imports into unchanged files and miss breakage in reverse dependencies.
It only runs when the local venv matches `uv.lock` (`uv sync --check`); a drifted venv produces spurious errors CI won't report, so preflight skips instead.
ty does not run inside `hogli ci:preflight`; it runs through lint-staged before commit.

## Manual usage

```bash
uv run --no-sync ty check path/to/file.py
uv run --no-sync mypy --cache-fine-grained .
hogli ci:preflight
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
- Uses its incremental cache to speed up repeat local checks (first run per checkout is the slow one)
- Runs repo-wide both as a preflight advisory and in CI
- Blocks CI on type errors; local preflight findings never block a push

## Configuration

ty rule categories where ty disagrees with mypy on idiomatic Django/DRF code are suppressed in `pyproject.toml` under `[tool.ty.rules]`.
This replaced the earlier `ty-baseline.txt` filter file (removed in #55368).
Add a new `<rule> = "ignore"` there if CI surfaces a spurious ty category.
