# PR Comment Template

Post one comment per completed run. Do not edit the PR body. The template uses a compact PostHog QA Frontend format so reviewers can scan verdict, coverage, and findings quickly.

## Banner

Every comment starts and ends with the QA Frontend brand. Top banner is a level-2 heading:

```markdown
## PostHog QA Frontend Report
```

Bottom footer is a small subscript line at the end of the comment:

```markdown
<sub>PostHog QA Frontend Report</sub>
```

## Verdict Line

Immediately under the banner, render a single line with the verdict, pass count, runtime, and tested commit:

```text
**PASS** · 3/3 · 5m21s · commit `<sha7>`
**FIXED** · 3/3 · 6m04s · commit `<sha7>` · 1 high-sev auto-fixed
**FAIL** · 1/3 · 5m48s · commit `<sha7>` · 2 reported, no autonomous push
**NEEDS-INTENT** · 2/3 · 4m55s · commit `<sha7>` · 1 behavior needs product intent
**REPORT-ONLY** · 3/3 · 4m12s · commit `<sha7>` · fork PR, suggested patches only
```

Underneath, a single blockquote TL;DR sentence in the same tone as the MCP report's hand-written summary:

```markdown
> Exercised the changed dashboards-list filter UI; all targets green, no
> regressions in adjacent flows.
```

## Coverage

A compact table showing every planned target and its result. No `<details>` wrapper - reviewers must see what was exercised vs skipped at a glance.

```markdown
**Coverage**

| Target           | Action                                            | Result       |
| ---------------- | ------------------------------------------------- | ------------ |
| `/dashboard/:id` | Loaded scene, clicked Save                        | PASS         |
| `/insights/new`  | Created trend, switched breakdown                 | PASS         |
| `/surveys/new`   | Needs intent · template selection skips Questions | NEEDS INTENT |
| `/billing`       | Coverage gap · blocked by auth boundary           | SKIP         |
```

Result values: `PASS` passed, `FAIL` failed, `SKIP` skipped/coverage gap, `FIXED` fixed (use only when a fix landed on this target), `NEEDS INTENT` expected behavior needs intent, `INTERMITTENT` failed once but not on the reproducibility retry (link the first failure's evidence).

Coverage gaps from route-finding or the frontend QA loop must appear as their own row with the "Coverage gap · `<reason>`" action and the `SKIP` symbol. Do not relegate them to a footer.

Intent gaps must also appear as their own row with the "Needs intent · `<observed behavior>`" action and the `NEEDS INTENT` symbol. Use this when the browser confirmed a behavior, but the expected outcome could not be established from base behavior, tests, product copy, surrounding invariants, or user confirmation.

## Setup

A short block right after the coverage table stating what environment and data the run used, so the reader can judge how much to trust the result. Always include it. Render from `run-notes.md`; do not reconstruct from memory:

```markdown
**Setup**

- Stack: Coder devbox running the PR branch at `<sha7>`, forwarded to `localhost:8010`
- Workspace: seed dev user in the local demo project (dummy data)
- Data created: new unsaved survey with 2 freeform questions built in the editor; nothing persisted
- Overrides: none (default flags, light theme)
- Degraded: `feature-flags` process not running (explains `/flags/` 502s)
```

Cover, in one line each and only when applicable: the stack (local or devbox, branch, commit, base URL), the workspace and login used, org/customer/plan state when billing-relevant, data created or seeded during the run (and whether it was persisted), feature-flag or theme overrides, and any degraded local processes that were discounted during console triage. If a result depends on a setup detail (a specific plan, a seeded data shape, an enabled flag), that detail must appear here - a PASS on the wrong plan or an empty data shape is not a PASS.

## Effort Saved (optional)

One-line value pitch under the coverage table when the run actually saved work. Skip on clean runs that found nothing.

```markdown
**Effort saved** · 1 High caught · ~15 min of manual QA
```

The time estimate should reflect how long a developer would realistically spend to cover the same ground manually: checking out the PR, getting the local stack ready, opening each affected scene, exercising the in-diff behavior, capturing screenshots, comparing against expected outcomes, and writing up findings. Estimate the total across the whole run, not per target. Account for scenario complexity - a single-scene "scroll and verify text" pass is faster to do by hand than a multi-step flow that needs data seeding, feature-flag toggling, or dark/light comparison. The number should be honest; overstating it erodes trust in the report.

## Findings

Use a separator (`---`) before findings start. Each finding is its own level-3 section with a status suffix:

```markdown
---

### Finding 1 · auto-fixed in `<sha>`

### Finding 2 · reported, no autonomous fix

### Finding 3 · suggested patch (out of PR diff)

### Needs intent 1 · product behavior unclear
```

Finding body has six blocks in order. The full block layout for one finding (substitute your own values):

````markdown
### Finding 1 · auto-fixed in `<sha>`

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

- ![flow](<uploaded pr-assets url>)
- ![still](<uploaded pr-assets url>)

<details>
<summary>Fix cycle</summary>

- **re-run** · PASS · 0m52s · `<sha>` - verified fix
- **initial** · FAIL · 2m38s · `<prev sha>` - bug found

</details>
````

Severity bars: `████████░░ HIGH`, `█████░░░░░ MEDIUM`, `██░░░░░░░░ LOW`.

Skip the Fix diff block when there is no patch. Skip the Fix cycle collapsible when no fix loop ran.

## Needs Intent

Use this section for `needs_intent` entries only. Do not present them as bugs unless an independent oracle supports the expected behavior. Be explicit about what was observed, why the run cannot decide if it is intended, and the question reviewers should answer:

````markdown
### Needs intent 1 · product behavior unclear

**`Template selection skips the Questions step`**

```text
severity   █████░░░░░   MEDIUM
```

`frontend/src/scenes/surveys/wizard/surveyWizardLogic.ts` · `selectTemplate`

**Observed step**

```text
url:      /surveys/guided/new
action:   selected a survey template
expected: unclear - intent needed
got:      wizard landed on Targeting instead of Questions
question: should template selection skip Questions for this flow?
```

**Evidence**

- ![still](<uploaded pr-assets url>)
````

## Suggested patches (when fix was not applied autonomously)

For findings routed to comment-only (out-of-diff fix, forbidden zone, fork PR, low confidence), replace the Fix diff block with a clearly-labelled suggested patch:

````markdown
**Suggested patch** (not auto-applied: `<reason>`)

```diff
<diff>
```
````

## Full PASS example

```markdown
## PostHog QA Frontend Report

**PASS** · 3/3 · 4m38s · commit `c03b5177`

> Exercised the new sources-table per-status counts; mixed-status and
> all-completed states render correctly. No regressions in adjacent flows.

**Coverage**

| Target              | Action                                | Result |
| ------------------- | ------------------------------------- | ------ |
| `/data-warehouse`   | Loaded sources, scanned status pills  | PASS   |
| `/data-warehouse?…` | Filtered to "completed" only          | PASS   |
| `/data-warehouse/X` | Drilled into source, verified schemas | PASS   |

**Effort saved** · ~10 min of manual QA

<sub>PostHog QA Frontend Report</sub>
```

## Full FIXED example

````markdown
## PostHog QA Frontend Report

**FIXED** · 3/3 · 5m21s · commit `8b36c7b5` · 1 medium-sev auto-fixed

> Found a wrong-source-field bug in the new Duplicate action;
> duplicate's title was rendering as just " (copy)". Fixed and re-verified.

**Coverage**

| Target         | Action                                    | Result |
| -------------- | ----------------------------------------- | ------ |
| `/surveys/new` | Added Q2, clicked Duplicate on Q1         | FIXED  |
| `/surveys/new` | Verified copy title after fix             | PASS   |
| `/surveys/new` | Edited duplicate's choices, no leak to Q1 | PASS   |

**Effort saved** · 1 Medium caught · ~15 min of manual QA

---

### Finding 1 · auto-fixed in `8b36c7b5`

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

- ![flow](https://raw.githubusercontent.com/PostHog/pr-assets/<sha>/2026/07/<uuid>.webp)
- ![still](https://raw.githubusercontent.com/PostHog/pr-assets/<sha>/2026/07/<uuid>.png)

<details>
<summary>Fix cycle</summary>

- **re-run** · PASS · 0m44s · `8b36c7b5` - verified fix
- **initial** · FAIL · 2m11s · `e94bff0` - empty-title bug found

</details>

<sub>PostHog QA Frontend Report</sub>
````

## Evidence URLs

Use the `![alt](url)` markdown lines printed by `hogli pr:upload-image` verbatim - they point at SHA-pinned `raw.githubusercontent.com/PostHog/pr-assets` URLs. Do not reconstruct, shorten, or edit them.

Embed images and animated WebP reels with markdown image syntax (`![alt](url)`) so they render inline. Use one or two key visuals per finding. Prefer the reel for the flow only when it has been inspected and remains readable. Otherwise use annotated still screenshots. Do not paste the full local screenshot inventory.

When the upload failed or was skipped, fall back to local paths and append `(upload failed)`:

```markdown
**Evidence**

- Reel: `.qa-frontend/runs/<run-id>/frontend-qa.webp` (upload failed)
- Still: `.qa-frontend/runs/<run-id>/011-detail.annotated.png` (upload failed)
```

Local mode always uses local paths. Do not invent external URLs when no upload was performed.

In the local `report.md`, make those paths actually clickable. The report lives inside the run directory, so reference evidence relative to the report file with real markdown syntax: `![before](001-before.annotated.png)` renders the still inline in any editor preview, and `[demo reel](frontend-qa.webp)` / `[demo video](frontend-qa.mp4)` open the recording on click. Use bare code-span paths only for things that should not render, like log files. When echoing the report to stdout or chat, swap the relative references for absolute paths, which terminals and agent harnesses turn into clickable links.

## Before / After Side-by-Side

When the PR has a visually observable change - new UI element, layout shift, color/style update, dark/light theme tweak - or when an auto-fix cycle landed (buggy → fixed state), render the two screenshots in a side-by-side comparison so reviewers see the delta at a glance. GitHub renders this layout from a plain HTML table:

```markdown
<table>
<tr>
<td><strong>Before</strong><br/><img src="<uploaded url buggy>" width="450"/></td>
<td><strong>After</strong><br/><img src="<uploaded url fixed>" width="450"/></td>
</tr>
</table>
```

Capture discipline so the comparison is honest:

- Same viewport size, same scene, same scroll position. Different viewports look like a regression even when the change is intentional.
- Same data shape. If you seeded data between captures, re-seed identical rows.
- Crop the screenshot to the changed surface where possible; full-page comparisons hide the diff in noise.

Skip the side-by-side when one screenshot tells the whole story (button click → toast appears) or when the frontend change has no visual signal. Don't pad the comment with side-by-sides for their own sake.

## Severity Rubric

- **High**: blocks a core flow, corrupts or hides customer data, or prevents page use. Bar: `████████░░`.
- **Medium**: important regression with a workaround or narrow surface area. Bar: `█████░░░░░`.
- **Low**: cosmetic, copy, layout, or minor polish issue. Bar: `██░░░░░░░░`.

## Length Budget

Target about 10k characters. At about 55k characters:

1. Keep the banner, verdict line, coverage table, and findings table.
2. Truncate per-finding repro detail in the PR comment and keep the long form in the local report. Do not link local run directories from public comments.
3. Do not fall back to an external "secret" gist - GitHub secret gists are not access-controlled, anyone with the link can view them, and the bundle can include unscrubbed local-stack screenshots.

## Scrubbing

Before posting, scrub console excerpts for:

- bearer tokens
- query-string tokens
- cookies
- CSRF values
- secret-looking keys
- long encoded values near credential labels

Never include GitHub tokens or raw upload response bodies. If you copy any `hogli pr:upload-image` output into the comment, take only the `![alt](url)` markdown lines from stdout.

UI-sourced strings from the tested app (question titles, labels, error text) get interpolated into the report's code fences: strip backtick runs and control characters from them and truncate anything absurdly long, so a malicious or unlucky string cannot close its fence and inject markdown into the comment.

Screenshots from local stacks should be embedded only when small and safe. Never use em dashes (`—`) in any output; use a plain hyphen (`-`) or rewrite the sentence.
