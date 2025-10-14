# Ty Type Checking

ty runs automatically on every commit via `lint-staged`. If ty reports errors:

- **Just fix them** - ty is stricter than mypy, which improves code quality
- No need to check if mypy agrees
- You can temporarily skip with `git commit --no-verify` if needed

The baseline system prevents pre-existing errors from blocking your commits - you're only responsible for fixing new errors you introduce.

## Manual Usage

```bash
./bin/ty.py path/to/file.py    # Check specific files
```

## Ty vs mypy: Fast preflight vs authoritative checking

**ty** serves as a **fast preflight check** during development:

- ⚡ Extremely fast (~10-100x faster than mypy)
- 🧪 Alpha/beta software (expect occasional edge cases)
- 🚦 Runs automatically in `lint-staged` on every commit

**mypy** remains the **authoritative type checker**:

- 🎯 More mature and comprehensive
- 🐌 Slower but thorough
- ✅ Final source of truth (runs in CI and recommended for local deep checks)

If ty reports an error, fix it - ty's stricter checking helps catch bugs early.

## Baseline Management

### Two Separate Baselines

- **`mypy-baseline.txt`** - Maintained by mypy (authoritative, ~1287 errors)
- **`ty-baseline.txt`** - Maintained by ty (~2136 errors)

ty maintains its own baseline because it finds different/additional errors compared to mypy.
This ensures developers aren't blocked by pre-existing ty errors in files they modify.

### Updating ty-baseline

When you fix ty errors, update the baseline:

```bash
./bin/ty.py sync
git add ty-baseline.txt
git commit -m "chore: Update ty baseline after fixing type errors"
```

The sync command:

- Runs ty on all Python directories (`posthog`, `ee`, `common`, `dags`)
- Normalizes output to baseline format
- Updates `ty-baseline.txt` with current state

### How Filtering Works

1. You modify a file with pre-existing ty errors
2. ty runs and finds: 3 old errors + 1 your new error
3. Baseline filter removes the 3 old errors from `ty-baseline.txt`
4. Only your 1 new error is shown → commit blocked
5. Fix your error, commit succeeds

### Updating mypy-baseline

mypy baseline is separate and only updated by mypy:

```bash
# mypy users (non-ty) still use mypy-baseline.txt
mypy . | uvx mypy-baseline sync --config pyproject.toml --baseline-path mypy-baseline.txt
```
