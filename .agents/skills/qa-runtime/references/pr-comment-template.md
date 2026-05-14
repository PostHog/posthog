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

| Target           | Type         | Action                            | Outcome          |
| ---------------- | ------------ | --------------------------------- | ---------------- |
| `/dashboard/:id` | Browser      | Loaded dashboard and clicked Save | Passed           |
| `/billing`       | Coverage gap | Could not load (auth boundary)    | Skipped (reason) |

</details>

Run metadata: tested `<sha>` at `<timestamp>` using `<BASE_URL>`.
```

Coverage gaps from the walker or runtime loop must appear in this table as
`Coverage gap` rows with an explicit "Skipped (reason)" outcome. Do not
mention them only in a footer note - reviewers need to see what was _not_
exercised alongside what was.

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

- GIF: ![flow](https://res.cloudinary.com/dmukukwp6/image/upload/v.../qa_posthog_pr58423_a3f4b2c_001_flow_overview_<hash>.gif)
- Screenshots: ![finding](https://res.cloudinary.com/dmukukwp6/image/upload/v.../qa_posthog_pr58423_a3f4b2c_002_save_button_no_toast_<hash>.png)
- Console: `<scrubbed excerpt or "none">`

Fix status: auto-fixed in `<commit>` and re-verified with the same MCP flow.
```

Evidence URLs come from `upload-manifest.json` produced by
`scripts/upload-evidence.py`. Use the `url` field from each `uploaded` entry
verbatim. The script uploads directly to Cloudinary, so the URL lives on
`res.cloudinary.com/<cloud_name>/image/upload/v.../<public_id>.<ext>` with
dashes preserved. The local filename in `public_id` is for traceability only;
the embeddable URL is always the `url` field.

Embed images and GIFs using markdown image syntax (`![alt](url)`) so they
render inline in the PR thread. Use one or two key visuals - the GIF for the
flow and one screenshot per finding. Do not paste the full local screenshot
inventory.

When `upload-manifest.json` reports `skipped_no_env: true` or lists files under
`failed`, fall back to local paths and append `(upload failed)`:

```markdown
Evidence:

- GIF: `.qa-runtime/runs/<run-id>/runtime-qa.gif` (upload failed)
- Screenshots: `.qa-runtime/runs/<run-id>/011-tab-customization.png` (upload failed)
```

Local mode always uses local paths. Do not invent external URLs when no upload
was performed.

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

Never include `CLOUDINARY_URL`, the Cloudinary API key/secret, or raw upload
response bodies. The upload script does not log these by default; if you copy
any script output into the comment, double-check the line you paste.

Screenshots from local stacks should be embedded only when small and safe.
Prefer secret gist links for the full bundle.
