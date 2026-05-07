# Devex semgrep rules

Tracking-style rules: surface "not yet ideal" code as a list, without blocking master.
Rules in this directory are run by the `semgrep-devex` job in `ci-security.yaml` in two passes:

1. **Tracked warnings** — `semgrep --severity=WARNING` runs all `severity: WARNING` rules and prints findings. Does not fail CI. Each finding is one entry in the "still to migrate" backlog.
2. **Graduated errors** — `semgrep --severity=ERROR --error` runs all `severity: ERROR` rules. Fails CI on any finding. This is the regression guard for migrations that have hit zero findings.

## Graduation flow

When the backlog for a rule hits zero, promote the rule from warning to error so the codebase stays clean:

1. Verify locally that `semgrep --config .semgrep/devex-rules/<rule>.yaml common/ ee/ posthog/ products/` returns zero findings.
2. Edit the rule file: change `severity: WARNING` to `severity: ERROR`.
3. Update the rule's `message:` to drop the "tracked, not blocking" phrasing — it's now blocking.
4. Land the change. Future regressions fail CI on `semgrep-devex`.

The rule stays in `.semgrep/devex-rules/`; only the severity flips. That's intentional — the directory keeps tracking-or-recently-graduated rules together, and the severity field is the authoritative blocking signal.

## Rules in this directory

- `admin-product-import.yaml` — flags central admin entries (`from products.X.…` inside `posthog/admin/**`) for product-owned models. Migration playbook: see `/move-admins-to-product` skill at `.agents/skills/move-admins-to-product/SKILL.md`.

## Conventions for new rules

- Start at `severity: WARNING`. Rules in this directory exist precisely because the codebase isn't at zero findings yet.
- Include the migration playbook (or a pointer to a skill) in the rule's `message:` field. The rule fires in CI output; the message is what reviewers and authors see.
- Keep the rule's `paths.include:` tight — flag only the locations that map to a real "should move" signal. False positives in a tracking rule still cost reviewer attention.
- If a finding genuinely shouldn't move (legitimate central code), use `# nosemgrep: <rule-id>` inline — the same escape hatch the security rules use.
