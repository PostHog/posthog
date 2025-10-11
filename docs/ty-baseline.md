# Ty Type Checking (Opt-In Alpha)

## ⚠️ Opt-In Only

ty type checking is currently **opt-in**. To enable:

```bash
git config posthog.enableTy true
```

Once enabled, ty will run automatically on your commits via `lint-staged`. If ty reports errors:

- **Just fix them** - ty is stricter than mypy, which improves code quality
- No need to check if mypy agrees
- You can temporarily skip with `git commit --no-verify` if needed

To disable:

```bash
git config --unset posthog.enableTy
```

## Why Opt-In?

ty finds errors in ~333 files not in mypy baseline (~73% of files it flags). Making it opt-in:

- Doesn't block developers unexpectedly
- Lets volunteers improve type safety gradually
- Provides time to understand ty vs mypy differences
- Embraces ty's stricter checking as an improvement, not a burden

## Manual Usage

You can run ty manually even without opting in:

```bash
./bin/ty.py path/to/file.py    # Check specific files
```

## Ty vs mypy: Fast preflight vs authoritative checking

**ty** serves as a **fast preflight check** during development:

- ⚡ Extremely fast (~10-100x faster than mypy)
- 🧪 Alpha/beta software (expect occasional edge cases)
- 🔒 **Opt-in only** - enable via `git config posthog.enableTy true`
- 🚦 Runs automatically in `lint-staged` when opted in

**mypy** remains the **authoritative type checker**:

- 🎯 More mature and comprehensive
- 🐌 Slower but thorough
- ✅ Final source of truth (runs in CI and recommended for local deep checks)

If ty reports an error, fix it - ty's stricter checking helps catch bugs early.

## Baseline Management

### Two Separate Baselines

- **`mypy-baseline.txt`** - Maintained by mypy (authoritative, ~1287 errors)
- **`ty-baseline.txt`** - Maintained by ty (opt-in users only, ~2136 errors)

ty maintains its own baseline because it finds different/additional errors compared to mypy.
This ensures opted-in users aren't blocked by pre-existing ty errors in files they modify.

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
