# Devex semgrep rules

Devex / hygiene rules for the PostHog codebase. The `semgrep-devex` job in `ci-security.yaml` reads them once, into `semgrep-devex.json`, and `bin/semgrep_devex_report.py` grades that one report in four passes. A `semgrep` run starts from a cold cache, because the container is discarded, so a second run over the same tree re-parses it.

1. **Warnings (informational)** — the `severity: WARNING` findings. They appear in the CI run output but the step does not fail. Use this mode when a rule has a non-zero backlog of existing violations — the list shows up in CI without blocking master while the codebase is cleaned up.
2. **Errors (blocking)** — any `severity: ERROR` finding outside `products/desktop/` fails CI. Use this mode for hard regression guards: patterns that should never appear, or migration-style rules whose backlog has been cleaned up.
3. **New warnings (blocking, PRs only)** — a second `semgrep` run with `--baseline-commit` set to the PR base, plus `--error`. It scopes itself to the changed files, so it is not part of the shared scan. Findings that already exist on the base are grandfathered; findings the PR introduces fail the job. This stops the bleeding on backlogged rules while the backlog is worked down. Caveat: moving or renaming a file makes its grandfathered findings look new to the baseline diff — either fix them as part of the move or exempt them with `# nosemgrep: <rule-id>`.
4. **New test sleeps (blocking, PRs only)**: `no-fixed-sleeps-in-tests` runs with the same PR baseline on the Python files the PR changes, and its `paths.include` selects the test files. The step passes the files as explicit targets, because Semgrep skips `test/` and `tests/` directories by default.

## Picking a severity

Pick the severity that matches the rule's intent:

- **ERROR** when zero violations are expected — either because the pattern is genuinely new (regression guard) or because a previously-WARNING rule has been cleaned up.
- **WARNING** when there's a known non-zero backlog that will be migrated over time.

A WARNING rule typically gets flipped to ERROR once its backlog hits zero. The rule stays in `.semgrep/rules/devex/`; only the severity changes. To flip a rule:

1. Verify locally that `semgrep --config .semgrep/rules/devex/<rule>.yaml bin/ common/ docs/onboarding/ ee/ frontend/ hog/ packages/ posthog/ products/ services/ tools/` returns zero findings.
2. Edit the rule file: change `severity: WARNING` to `severity: ERROR`.
3. Update the rule's `message:` to drop any "informational, not blocking" phrasing — it's now blocking.

## Conventions for new rules

- Decide severity by expected finding count: zero → ERROR; non-zero → WARNING.
- Include the migration playbook (or a pointer to a skill) in the rule's `message:` field — that's what reviewers and authors see when the rule fires.
- Scope with `paths.include:` rather than relying only on `paths.exclude:` — narrower scope means faster scans and clearer intent.
- For legitimate exceptions, prefer `paths.exclude:` for categorical cases (whole dirs/files) and `# nosemgrep: <rule-id>` for case-by-case exemptions at the call site.

## Per-file baseline ratchets

A WARNING rule grandfathers its backlog through `--baseline-commit`, so the backlog has no count that a migration can lower, and a moved file looks new.
For a migration that runs over many PRs, use a per-file baseline instead:

1. Give the rule `severity: INFO`. The passes above select WARNING and ERROR only, so they do not report it.
2. Check in a baseline file that lists `<path> <count>` for each file with findings. `bin/semgrep_ratchet.py --update` writes it from `semgrep --json` output.
3. Add a step to the `semgrep-devex` job that extracts the rule's findings from the shared report with `bin/semgrep_devex_report.py ratchet-input --rule <rule-id>`, then runs `bin/semgrep_ratchet.py --findings <json> --baseline <file>`.

The ratchet fails when a file has more findings than its baseline count, and also when it has fewer. So each migration PR lowers the count or removes the line.

| Rule                            | Baseline                                         |
| ------------------------------- | ------------------------------------------------ |
| `integration-model-through-sdk` | `posthog/integrations/model_access_baseline.txt` |
