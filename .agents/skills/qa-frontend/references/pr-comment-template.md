# PR Comment Template

Post one comment per completed run. Do not edit the PR body. The template
mirrors the MCP Report style from the sibling qa-swarm skill so reviewers
recognize both reports as one product.

## Banner

Every comment starts and ends with the QA Swarm brand. Top banner is a
level-2 heading:

```markdown
## 🦔 PostHog QA Swarm · Frontend Report
```

Bottom footer is a small subscript line at the end of the comment:

```markdown
<sub>🦔 PostHog QA Swarm · Frontend Report</sub>
```

## Verdict Line

Immediately under the banner, render a single line with the verdict, pass
count, runtime, and tested commit:

```text
**🟢 PASS** · 3/3 · 5m21s · commit `<sha7>`
**🟡 FIXED** · 3/3 · 6m04s · commit `<sha7>` · 1 high-sev auto-fixed
**🔴 FAIL** · 1/3 · 5m48s · commit `<sha7>` · 2 reported, no autonomous push
**🟠 REPORT-ONLY** · 3/3 · 4m12s · commit `<sha7>` · fork PR, suggested patches only
```

Underneath, a single blockquote TL;DR sentence in the same tone as the MCP
report's hand-written summary:

```markdown
> Exercised the changed dashboards-list filter UI; all targets green, no
> regressions in adjacent flows.
```

## Coverage

A compact table showing every planned target and its result. No `<details>`
wrapper - reviewers must see what was exercised vs skipped at a glance.

```markdown
**Coverage**

| Target           | Action                                  | Result |
| ---------------- | --------------------------------------- | ------ |
| `/dashboard/:id` | Loaded scene, clicked Save              | ✅     |
| `/insights/new`  | Created trend, switched breakdown       | ✅     |
| `/billing`       | Coverage gap · blocked by auth boundary | ⏭     |
```

Result symbols: `✅` passed, `❌` failed, `⏭` skipped/coverage gap, `🛠`
fixed (use only when a fix landed on this target).

Coverage gaps from route-finding or the frontend QA loop must appear as their
own row with the "Coverage gap · `<reason>`" action and the `⏭` symbol. Do not
relegate them to a footer.

## Effort Saved (optional)

One-line value pitch under the coverage table when the run actually saved
work. Skip on clean runs that found nothing.

```markdown
**Effort saved** · 🎯 1 High caught · ⏱ ~15 min of manual QA
```

The time estimate should reflect how long a developer would realistically
spend to cover the same ground manually: checking out the PR, getting the
local stack ready, opening each affected scene, exercising the in-diff
behavior, capturing screenshots, comparing against expected outcomes, and
writing up findings. Estimate the total across the whole run, not per
target. Account for scenario complexity - a single-scene "scroll and
verify text" pass is faster to do by hand than a multi-step flow that
needs data seeding, feature-flag toggling, or dark/light comparison. The
number should be honest; overstating it erodes trust in the report.

## Findings

Use a separator (`---`) before findings start. Each finding is its own
level-3 section with a status suffix:

```markdown
---

### 🐛 Finding 1 · auto-fixed in `<sha>`

### 🐛 Finding 2 · reported, no autonomous fix

### 🐛 Finding 3 · suggested patch (out of PR diff)
```

Finding body has six blocks in order. The full block layout for one
finding (substitute your own values):

````markdown
### 🐛 Finding 1 · auto-fixed in `<sha>`

**`Save button in dashboard header does not fire onClick`**

```text
severity   ████████░░   HIGH
```

`frontend/src/scenes/dashboard/DashboardHeader.tsx` · `DashboardHeader`

```diff
- const handleSave = () => save
+ const handleSave = () => save()
```

**Failing step**

```text
url:      /dashboard/123
action:   clicked Save
expected: save toast appears, URL stays
got:      no UI change, no network call, no console error
```

**Evidence**

- ![flow](<cloudinary url>)
- ![still](<cloudinary url>)

<details>
<summary>📜 Fix cycle</summary>

- **re-run** · ✅ · 0m52s · `<sha>` - verified fix
- **initial** · ❌ · 2m38s · `<prev sha>` - bug found

</details>
````

Severity bars: `████████░░ HIGH`, `█████░░░░░ MEDIUM`, `██░░░░░░░░ LOW`.

Skip the Fix diff block when there is no patch. Skip the Fix cycle
collapsible when no fix loop ran.

## Suggested patches (when fix was not applied autonomously)

For findings routed to comment-only (out-of-diff fix, forbidden zone, fork
PR, low confidence), replace the Fix diff block with a clearly-labelled
suggested patch:

````markdown
**Suggested patch** (not auto-applied: `<reason>`)

```diff
<diff>
```
````

## Full PASS example

```markdown
## 🦔 PostHog QA Swarm · Frontend Report

**🟢 PASS** · 3/3 · 4m38s · commit `c03b5177`

> Exercised the new sources-table per-status counts; mixed-status and
> all-completed states render correctly. No regressions in adjacent flows.

**Coverage**

| Target              | Action                                | Result |
| ------------------- | ------------------------------------- | ------ |
| `/data-warehouse`   | Loaded sources, scanned status pills  | ✅     |
| `/data-warehouse?…` | Filtered to "completed" only          | ✅     |
| `/data-warehouse/X` | Drilled into source, verified schemas | ✅     |

**Effort saved** · ⏱ ~10 min of manual QA

<sub>🦔 PostHog QA Swarm · Frontend Report</sub>
```

## Full FIXED example

````markdown
## 🦔 PostHog QA Swarm · Frontend Report

**🟡 FIXED** · 3/3 · 5m21s · commit `8b36c7b5` · 1 medium-sev auto-fixed

> Found a wrong-source-field bug in the new Duplicate action;
> duplicate's title was rendering as just " (copy)". Fixed and re-verified.

**Coverage**

| Target         | Action                                    | Result |
| -------------- | ----------------------------------------- | ------ |
| `/surveys/new` | Added Q2, clicked Duplicate on Q1         | 🛠     |
| `/surveys/new` | Verified copy title after fix             | ✅     |
| `/surveys/new` | Edited duplicate's choices, no leak to Q1 | ✅     |

**Effort saved** · 🎯 1 Medium caught · ⏱ ~15 min of manual QA

---

### 🐛 Finding 1 · auto-fixed in `8b36c7b5`

**`Duplicate question's title is built from the wrong field`**

```text
severity   █████░░░░░   MEDIUM
```

`frontend/src/scenes/surveys/surveyLogic.tsx` · `duplicateQuestion` listener

```diff
-        question: `${original.description ?? ''} (copy)`,
+        question: `${original.question} (copy)`,
```

**Failing step**

```text
url:      /surveys/new
action:   clicked Duplicate on Question 1 ("Give us feedback…")
expected: new Question 2 titled "Give us feedback… (copy)"
got:      new Question 2 titled " (copy)" - empty title with stray space
```

**Evidence**

- ![flow](https://res.cloudinary.com/.../qa-posthog-pr58541-…-flow.gif)
- ![still](https://res.cloudinary.com/.../qa-posthog-pr58541-…-still.png)

<details>
<summary>📜 Fix cycle</summary>

- **re-run** · ✅ · 0m44s · `8b36c7b5` - verified fix
- **initial** · ❌ · 2m11s · `e94bff0` - empty-title bug found

</details>

<sub>🦔 PostHog QA Swarm · Frontend Report</sub>
````

## Evidence URLs

Use the `url` field from each `uploaded` entry in `upload-manifest.json`
verbatim. The script uploads directly to Cloudinary, so URLs live on
`res.cloudinary.com/<cloud>/image/upload/v.../<public_id>.<ext>` with dashes
preserved. The local filename in `public_id` is for traceability only; the
embeddable URL is always the `url` field.

Embed images and GIFs with markdown image syntax (`![alt](url)`) so they
render inline. Use one or two key visuals per finding - the GIF for the
flow and one still per finding. Do not paste the full local screenshot
inventory.

When `upload-manifest.json` reports `skipped_no_env: true` or lists files
under `failed`, fall back to local paths and append `(upload failed)`:

```markdown
**Evidence**

- GIF: `.qa-frontend/runs/<run-id>/frontend-qa.gif` (upload failed)
- Still: `.qa-frontend/runs/<run-id>/011-detail.png` (upload failed)
```

Local mode always uses local paths. Do not invent external URLs when no
upload was performed.

## Before / After Side-by-Side

When the PR has a visually observable change - new UI element, layout
shift, color/style update, dark/light theme tweak - or when an auto-fix
cycle landed (buggy → fixed state), render the two screenshots in a
side-by-side comparison so reviewers see the delta at a glance. GitHub
renders this layout from a plain HTML table:

```markdown
<table>
<tr>
<td><strong>Before</strong><br/><img src="<cloudinary url buggy>" width="450"/></td>
<td><strong>After</strong><br/><img src="<cloudinary url fixed>" width="450"/></td>
</tr>
</table>
```

Capture discipline so the comparison is honest:

- Same viewport size, same scene, same scroll position. Different
  viewports look like a regression even when the change is intentional.
- Same data shape. If you seeded data between captures, re-seed identical
  rows.
- Crop the screenshot to the changed surface where possible; full-page
  comparisons hide the diff in noise.

Skip the side-by-side when one screenshot tells the whole story
(button click → toast appears) or when the frontend change has no visual signal.
Don't pad the comment with side-by-sides for their own sake.

## Severity Rubric

- **High**: blocks a core flow, corrupts or hides customer data, or
  prevents page use. Bar: `████████░░`.
- **Medium**: important regression with a workaround or narrow surface
  area. Bar: `█████░░░░░`.
- **Low**: cosmetic, copy, layout, or minor polish issue. Bar:
  `██░░░░░░░░`.

## Length Budget

Target about 10k characters. At about 55k characters:

1. Keep the banner, verdict line, coverage table, and findings table.
2. Truncate per-finding repro detail and link the run dir for the long
   form.
3. Do not fall back to an external "secret" gist - GitHub secret gists are
   not access-controlled, anyone with the link can view them, and the
   bundle can include unscrubbed local-stack screenshots.

## Scrubbing

Before posting, scrub console excerpts for:

- bearer tokens
- query-string tokens
- cookies
- CSRF values
- secret-looking keys
- long encoded values near credential labels

Never include `CLOUDINARY_URL`, the Cloudinary API key/secret, or raw
upload response bodies. The upload script does not log these by default;
if you copy any script output into the comment, double-check the line you
paste.

Screenshots from local stacks should be embedded only when small and safe.
Never use em dashes (`—`) in any output; use a plain hyphen (`-`) or
rewrite the sentence.
