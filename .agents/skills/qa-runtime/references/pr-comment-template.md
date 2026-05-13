# PR Comment Template

Post one comment per completed run. Do not edit the PR body.

## Verdict Header

Use one of:

```text
QA runtime: PASS - no reproducible runtime issues found.
QA runtime: <N> fix(es) pushed - reproducible issues fixed and re-verified.
QA runtime: <N> finding(s) reported - no autonomous push.
QA runtime: fork PR read-only mode - findings reported as suggested patches.
```

## Structure

```markdown
QA runtime: PASS - no reproducible runtime issues found.

<details>
<summary>What was tested</summary>

| Target           | Type    | Action                            | Outcome |
| ---------------- | ------- | --------------------------------- | ------- |
| `/dashboard/:id` | Browser | Loaded dashboard and clicked Save | Passed  |

</details>

Run metadata: tested `<sha>` at `<timestamp>` using `<BASE_URL>`.
```

For findings:

```markdown
QA runtime: 1 fix pushed - reproducible issue fixed and re-verified.

<details>
<summary>What was tested</summary>

| Target           | Type    | Action       | Outcome                             |
| ---------------- | ------- | ------------ | ----------------------------------- |
| `/dashboard/:id` | Browser | Clicked Save | Failed before fix, passed after fix |

</details>

| #   | Severity | Target           | Status                   |
| --- | -------- | ---------------- | ------------------------ |
| 1   | High     | `/dashboard/:id` | Auto-fixed in `<commit>` |

## Finding 1 - Save button did not submit

Steps:

1. Open `/dashboard/:id`.
2. Click Save.
3. Expected: save toast appears.
4. Actual: button click produced no UI change.

Evidence:

- GIF: `.qa-runtime/runs/<run-id>/runtime-qa.gif` when generated
- Screenshots: `<one-or-two-human-readable-screenshot-paths>`
- Console: `<scrubbed excerpt or "none">`

Fix status: auto-fixed in `<commit>` and re-verified with the same MCP flow.
```

For clean runs, keep evidence concise. Mention the GIF and one or two key
screenshots. Do not list every local snapshot markdown file in the PR comment;
those are local debugging artifacts.

For suggested patches:

````markdown
Fix status: not auto-applied because the fix touched files outside the PR diff.

Suggested patch:

```diff
<diff>
```
````

## Severity Rubric

- High: blocks a core flow, corrupts/hides customer data, or prevents page use.
- Medium: important regression with a workaround or narrow surface area.
- Low: cosmetic, copy, layout, or minor polish issue.

## Length Budget

Target about 10k characters. At about 55k characters:

1. Keep the verdict, test plan, and findings table.
2. Upload the full evidence bundle/report as a secret gist.
3. Add a link to the secret gist.
4. Truncate repeated repro detail.

## Scrubbing

Before posting, scrub console excerpts for:

- bearer tokens
- query-string tokens
- cookies
- CSRF values
- secret-looking keys
- long encoded values near credential labels

Screenshots from local stacks should be embedded only when small and safe.
Prefer secret gist links for the full bundle.
