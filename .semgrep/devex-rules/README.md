# Devex semgrep rules

Devex / hygiene rules for the PostHog codebase. Run by the `semgrep-devex` job in `ci-security.yaml` in two passes:

1. **Warnings (informational)** — `semgrep --severity=WARNING` runs all `severity: WARNING` rules. Findings appear in the CI run output but the step does not fail. Use this mode when a rule has a non-zero backlog of existing violations — the list shows up in CI without blocking master while the codebase is cleaned up.
2. **Errors (blocking)** — `semgrep --severity=ERROR --error` runs all `severity: ERROR` rules and fails CI on any finding. Use this mode for hard regression guards: patterns that should never appear, or migration-style rules whose backlog has been cleaned up.

## Picking a severity

Pick the severity that matches the rule's intent:

- **ERROR** when zero violations are expected — either because the pattern is genuinely new (regression guard) or because a previously-WARNING rule has been cleaned up.
- **WARNING** when there's a known non-zero backlog that will be migrated over time.

A WARNING rule typically gets flipped to ERROR once its backlog hits zero. The rule stays in `.semgrep/devex-rules/`; only the severity changes. To flip a rule:

1. Verify locally that `semgrep --config .semgrep/devex-rules/<rule>.yaml common/ ee/ frontend/ posthog/ products/` returns zero findings.
2. Edit the rule file: change `severity: WARNING` to `severity: ERROR`.
3. Update the rule's `message:` to drop any "informational, not blocking" phrasing — it's now blocking.

## Conventions for new rules

- Decide severity by expected finding count: zero → ERROR; non-zero → WARNING.
- Include the migration playbook (or a pointer to a skill) in the rule's `message:` field — that's what reviewers and authors see when the rule fires.
- Scope with `paths.include:` rather than relying only on `paths.exclude:` — narrower scope means faster scans and clearer intent.
- For legitimate exceptions, prefer `paths.exclude:` for categorical cases (whole dirs/files) and `# nosemgrep: <rule-id>` for case-by-case exemptions at the call site.
