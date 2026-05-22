# Expected Behavior

The diff is evidence, not the spec. Browser QA must distinguish:

- **Diff behavior** - what the edited code appears to make the UI do.
- **Expected behavior** - what should be correct for users.
- **Observed behavior** - what the browser actually did.

Do not mark a case PASS just because observed behavior matches the edited code.
PASS requires an expected behavior with a source independent of the changed
lines.

## Oracle Sources

Use the strongest available source:

1. Base behavior: compare the same file or flow from the base ref.
2. Existing tests, stories, fixtures, or snapshot names.
3. Product copy, step labels, route names, breadcrumbs, empty states, and nearby
   comments.
4. Invariants in surrounding code: ordered step arrays, validation rules,
   permission gates, feature-flag branches, or URL sync contracts.
5. User confirmation in local mode.

For local mode, inspect base code when the diff changes flow or state:

```bash
git show "$LOCAL_BASE_REF:path/to/changed-file.tsx"
git grep -n "<changed action or selector>" "$LOCAL_BASE_REF" -- path/to/area
```

For PR mode, use the PR base branch or `gh pr diff` context, then read nearby
current code. If base inspection is unavailable, record that limitation.

## Case Fields

Every behavior case should carry these fields in `run-notes.md`:

```json
{
  "diff_behavior": "Selecting a template now jumps to Targeting",
  "risk": "Users may skip question review and create surveys with defaults",
  "expected_behavior": "Selecting a template should open Questions first",
  "oracle_source": "base reducer selected 'questions'; WIZARD_STEPS order is template -> questions -> where -> when",
  "oracle_confidence": "high"
}
```

`oracle_confidence`:

- `high` - base behavior, test expectation, or explicit invariant supports the
  expected behavior.
- `medium` - multiple weaker product signals agree, but no direct test/base
  assertion exists.
- `unclear` - the expected behavior cannot be established without intent.

## Ambiguity Handling

When `oracle_confidence` is `unclear`, do not force a pass/fail verdict.

Local mode:

- Ask the user before finalizing PASS/FAIL.
- Include the observed behavior, risk, and why intent is unclear.
- If the user confirms it is intended, treat the case as PASS with
  `oracle_source: user confirmation`.
- If the user says it is unintended, record a finding and continue the normal
  retry/fix rules.

PR mode:

- Do not block the run waiting for the user.
- Add a `needs_intent` item to `findings.json`.
- Include it as a visible row in the PR comment coverage table.
- Mention the observed behavior and uncertainty in the report. Do not label the
  run clean PASS when meaningful behavior intent is unresolved.

Use this `needs_intent` shape:

```json
{
  "kind": "needs_intent",
  "severity": "medium",
  "confidence": "medium",
  "target": "/surveys/guided/new",
  "step": "Select a survey template",
  "expected": "Unclear - intent needed",
  "actual": "Template selection jumps to Targeting",
  "evidence": ["<screenshot path>"],
  "status": "needs-intent",
  "question": "Should template selection skip Questions and land on Targeting?"
}
```

## Wizard Step Example

Diff:

```diff
- selectTemplate: () => 'questions'
+ selectTemplate: () => 'where'
```

Bad QA plan:

```json
{
  "diff_behavior": "Selecting a template should place the user on Targeting",
  "expected_behavior": "Selecting a template should place the user on Targeting",
  "oracle_source": "changed reducer"
}
```

The changed reducer is not a valid oracle.

Better QA plan:

```json
{
  "diff_behavior": "Selecting a template now jumps to Targeting",
  "risk": "Users may skip reviewing default questions",
  "expected_behavior": "Selecting a template should open Questions first",
  "oracle_source": "base reducer selected 'questions'; WIZARD_STEPS order keeps Questions before Targeting",
  "oracle_confidence": "high",
  "action": "Open /surveys/guided/new, select a template, inspect the active step",
  "evidence": "Screenshot of active step after selection"
}
```

If product intent might have changed but the diff has no comment, test, copy, or
PR description explaining the new order, report the observation as a finding or
`needs_intent` rather than PASS.
