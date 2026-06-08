# Ty Type Checking

ty runs in CI as an informational check to evaluate its usefulness vs mypy. If you see ty annotations on your PR:

- Review the feedback — ty often catches real type issues
- Share your experience in #team-devex
- ty warnings are informational and don't block CI

## Manual Usage

```bash
uv run ty check path/to/file.py    # Check specific files
uv run ty check posthog ee         # Check directories
```

## Ty vs mypy: Fast trial vs authoritative checking

**ty** is currently in trial mode:

- Extremely fast (~10-100x faster than mypy)
- Alpha software — expect edge cases
- Runs in CI only (non-blocking) to gather feedback
- Uses GitHub problem matcher to show warnings inline

**mypy** remains the **authoritative type checker**:

- More mature and comprehensive
- Slower but thorough
- Final source of truth (runs in CI and blocks on errors)
- Recommended for local deep checks

This trial helps us evaluate whether ty should become a blocking check in the future.

## Configuration

ty rule categories where ty disagrees with mypy on idiomatic Django/DRF code
are suppressed in `pyproject.toml` under `[tool.ty.rules]`. This replaced the
earlier `ty-baseline.txt` filter file (removed in #55368). Add a new
`<rule> = "ignore"` there if CI surfaces a spurious ty category.
