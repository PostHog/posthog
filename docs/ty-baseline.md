# Ty type checking workflow

This repository runs [ty](https://docs.astral.sh/ty/) alongside `mypy-baseline`
to gate Python changes in pre-commit hooks while allowing existing issues to be
suppressed in `mypy-baseline.txt`.

## Ty vs mypy: Fast preflight vs authoritative checking

**ty** serves as a **fast preflight check** during development:

- ⚡ Extremely fast (~10-100x faster than mypy)
- 🧪 Alpha/beta software (expect occasional edge cases)
- 🚦 Runs automatically in `lint-staged` to catch obvious type errors early

**mypy** remains the **authoritative type checker**:

- 🎯 More mature and comprehensive
- 🐌 Slower but thorough
- ✅ Final source of truth (runs in CI and recommended for local deep checks)

If ty reports an error, you should generally fix it. However, in rare cases where
ty and mypy disagree, mypy's judgment takes precedence.

## Running ty locally

Ty runs automatically on staged Python files via `lint-staged`. You can invoke
the helper directly for ad-hoc checks:

```bash
./bin/ty.py path/to/file.py
```

The helper normalizes ty's diagnostics and filters anything already tracked in
`mypy-baseline.txt` so that only new problems surface.

## Updating the baseline

**⚠️ ty sync is currently disabled during the alpha phase.**

Since ty is alpha software and may have different diagnostic outputs than mypy,
only mypy should update the authoritative baseline:

```bash
# Use mypy-baseline directly for baseline updates
uvx mypy-baseline sync --config pyproject.toml --baseline-path mypy-baseline.txt

# Or use mypy directly (slower but authoritative)
mypy . | mypy-baseline sync --config pyproject.toml --baseline-path mypy-baseline.txt
```

This ensures the baseline remains consistent with mypy (the authoritative type
checker) while ty serves as a fast preflight check.
