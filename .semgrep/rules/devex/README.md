# Devex semgrep rules

Devex / hygiene rules for the PostHog codebase. Run by the `semgrep-devex` job in `ci-security.yaml` in three passes:

1. **Warnings (informational)** — `semgrep --severity=WARNING` runs all `severity: WARNING` rules. Findings appear in the CI run output but the step does not fail. Use this mode when a rule has a non-zero backlog of existing violations — the list shows up in CI without blocking master while the codebase is cleaned up.
2. **Errors (blocking)** — `semgrep --severity=ERROR --error` runs all `severity: ERROR` rules and fails CI on any finding. Use this mode for hard regression guards: patterns that should never appear, or migration-style rules whose backlog has been cleaned up.
3. **New warnings (blocking, PRs only)** — the WARNING rules run again with `--baseline-commit` set to the PR base, plus `--error`. Findings that already exist on the base are grandfathered; findings the PR introduces fail the job. This stops the bleeding on backlogged rules while the backlog is worked down. Caveat: moving or renaming a file makes its grandfathered findings look new to the baseline diff — either fix them as part of the move or exempt them with `# nosemgrep: <rule-id>`.

## Picking a severity

Pick the severity that matches the rule's intent:

- **ERROR** when zero violations are expected — either because the pattern is genuinely new (regression guard) or because a previously-WARNING rule has been cleaned up.
- **WARNING** when there's a known non-zero backlog that will be migrated over time.

A WARNING rule typically gets flipped to ERROR once its backlog hits zero. The rule stays in `.semgrep/rules/devex/`; only the severity changes. To flip a rule:

1. Verify locally that `semgrep --config .semgrep/rules/devex/<rule>.yaml bin/ common/ ee/ frontend/ packages/ posthog/ products/ services/ tools/` returns zero findings.
2. Edit the rule file: change `severity: WARNING` to `severity: ERROR`.
3. Update the rule's `message:` to drop any "informational, not blocking" phrasing — it's now blocking.

## Conventions for new rules

- Decide severity by expected finding count: zero → ERROR; non-zero → WARNING.
- Include the migration playbook (or a pointer to a skill) in the rule's `message:` field — that's what reviewers and authors see when the rule fires.
- Scope with `paths.include:` rather than relying only on `paths.exclude:` — narrower scope means faster scans and clearer intent.
- For legitimate exceptions, prefer `paths.exclude:` for categorical cases (whole dirs/files) and `# nosemgrep: <rule-id>` for case-by-case exemptions at the call site.
