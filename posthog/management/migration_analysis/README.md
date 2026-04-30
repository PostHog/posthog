# Migration risk analysis

`analyze_migration_risk` classifies unapplied Django migrations into three risk levels and publishes the result to CI consumers.
The classification is what powers the safety guidance you see on PRs that touch migrations.

## Risk levels

| Level        | Meaning                                                 |
| ------------ | ------------------------------------------------------- |
| Safe         | Brief or no lock; backwards compatible                  |
| Needs Review | May have performance impact (large nullable add, etc.)  |
| Blocked      | Causes locks, breaks compatibility, or no rollback path |

The level mapping lives in `posthog/management/migration_analysis/operations.py`. Adjust there, not in consumers.

## CI outputs (the public contract)

When CI runs the analyzer (in `.github/workflows/ci-backend.yml`), four artifacts are produced — anyone can consume any of them:

1. **PR comment** starting with `## 🔍 Migration Risk Analysis` (humans).
2. **GitHub check run** named `Migration risk` on the PR head commit:
   - `conclusion: success` if max level is Safe
   - `conclusion: neutral` if max level is Needs Review
   - `conclusion: failure` if max level is Blocked
   - `output.summary` carries the same markdown as the comment
3. **`migration_analysis.md`** uploaded as a workflow artifact (the rendered markdown).
4. **`migration_analysis.json`** uploaded alongside (`--output-json` schema):

   ```json
   {
     "summary": { "safe": 1, "needs_review": 0, "blocked": 0 },
     "max_level": "Safe",
     "migrations": [{ "label": "posthog.1125_x", "level": "Safe" }]
   }
   ```

The check run is the recommended programmatic surface: it is bound to the head commit at the GitHub API level, so consumers don't have to verify SHAs themselves. The JSON artifact is for cases that need per-migration detail.

The analyzer doesn't know who its consumers are. If you change the level mapping, the contract above stays the same — consumers continue to work without modification.

## Local invocation

```bash
python manage.py analyze_migration_risk                          # markdown to stdout
python manage.py analyze_migration_risk --fail-on-blocked        # CI mode
python manage.py analyze_migration_risk --output-json out.json   # also dump structured output
```
