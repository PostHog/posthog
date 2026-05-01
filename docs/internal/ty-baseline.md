# Ty Type Checking

ty runs in CI as an informational check to evaluate its usefulness vs mypy. If you see ty annotations in your PR:

- 👀 Review the feedback - ty often catches real type issues
- 📊 Share your experience in #team-devex
- ⚠️ ty warnings are informational and don't block CI

The baseline system filters out 567 pre-existing errors so you only see new issues introduced by your changes.

## Manual Usage

```bash
./bin/ty.py check path/to/file.py    # Check specific files
./bin/ty.py check posthog ee         # Check directories
```

## Ty vs mypy: Fast trial vs authoritative checking

**ty** is currently in trial mode:

- ⚡ Extremely fast (~10-100x faster than mypy)
- 🧪 Alpha software (v0.0.1a22 - expect edge cases)
- 📢 Runs in CI only (non-blocking) to gather feedback
- 🚨 Uses GitHub problem matcher to show warnings inline

**mypy** remains the **authoritative type checker**:

- 🎯 More mature and comprehensive
- 🐌 Slower but thorough
- ✅ Final source of truth (runs in CI and blocks on errors)
- 📍 Runs in CI and recommended for local deep checks

This trial helps us evaluate whether ty should become a blocking check in the future.

## Baseline Management

ty maintains its own baseline in `ty-baseline.txt` because it reports
different diagnostics than mypy. The baseline contains pre-existing ty errors
that won't trigger warnings in CI.

### Baseline Contents

The ty-baseline.txt contains:

- 91 redundant-cast (easy cleanup opportunities)
- 96 possibly-unbound-attribute (null safety checks)
- 119 missing-argument (real bugs requiring investigation)
- 52 deprecated warnings
- Plus other categories

About 50% are real bugs, 25% safety improvements, 25% trivial cleanups.

### Updating ty-baseline

When you fix ty errors across the codebase, update the baseline:

```bash
./bin/ty.py sync
git add ty-baseline.txt
git commit -m "chore: update ty baseline after fixing type errors"
```

The sync command runs ty on all Python directories and updates `ty-baseline.txt` with the current state.

### How Filtering Works in CI

1. CI runs ty on your changed files
2. ty finds errors (both old and new)
3. Baseline filter removes errors already in `ty-baseline.txt`
4. Only new errors you introduced are shown as warnings
5. CI always passes (ty is informational only)
