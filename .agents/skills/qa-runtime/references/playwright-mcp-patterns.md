# Playwright MCP Patterns

Use Playwright MCP as the runtime lens. Prefer user-visible assertions over
implementation assertions.

## Browser Flow Skeleton

1. `mcp__playwright__browser_navigate` to the target URL.
2. Read the action response. Navigation often includes an automatic snapshot.
3. Call `mcp__playwright__browser_snapshot` when the page state is unclear.
4. Interact by role, text, or accessible snapshot reference. Prefer visible
   controls over CSS selectors.
5. After each meaningful action, assert on UI state: changed text, toast,
   table row, modal state, URL change, or other visible result.
6. Capture a screenshot under `.qa-runtime/runs/<run-id>/`.
7. Read error-level console messages and network failures for the page.

## Snapshot Use

Start with the default snapshot. Deepen or scroll only when:

- The target element is likely below the fold.
- A collapsed panel hides the changed feature.
- The default snapshot has only loading or shell content.

Do not declare an element absent until you have checked the plausible scroll or
tab state.

## Console And Network Signals

Collect a baseline console snapshot after initial page load, then compare after
the changed action. Treat a new error as relevant only if it appears after the
target interaction or clearly belongs to the exercised endpoint.

Ignore known pre-existing third-party noise when it was present before the
action and does not affect the changed flow.

**Distinguish local-stack noise from PR-introduced errors.** Before scoring
any console output, check process-specific dev state through phrocs MCP:

- `mcp__phrocs__get_process_status(process="backend")`
- `mcp__phrocs__get_process_status(process="frontend")`
- The process implied by the error, for example `capture`, `feature-flags`,
  `temporal-worker`, or `mcp`

Do not rely on all-process status during startup; process-specific calls can
work while all-process status is still flaky. Common patterns to recognize and
discount, _only_ when the failing process explains them:

- 502s from `capture`, `capture-ai`, `capture-replay` endpoints when those
  processes are `stopped` or `crashed`
- 500s from invocations / hog flow paths when `cyclotron-janitor`,
  `cyclotron-worker`, or `temporal-worker` is down
- `Failed to load resource: 404` on `/decide`, remote-config, or
  feature-flag endpoints when `feature-flags` or `flags-consumer` is
  stopped
- CORS or font-CDN failures from third-party scripts in dev

Errors are in-scope (worth flagging) when they touch a code path the PR
actually changed, regardless of when they fire - including on initial
mount, before any user interaction. A scene that throws on first render
or fetches a wrong endpoint on load is a real bug, not pre-existing
noise. Errors at load time on the affected surface deserve the same
scrutiny as errors that follow a click or form submit.

Errors are out-of-scope (worth discounting) when they are explained by a
stopped local process from the list above, or by third-party scripts
unrelated to the diff.

When you discount errors, call out the triage explicitly in run notes and
in the PR comment ("All console errors traced to capture process being
stopped on this machine; no new errors introduced by this PR"). Silently
swallowing console output erodes trust in the report.

## API Checks

Prefer API checks through the authenticated Playwright page context so cookies
and CSRF state are naturally present. If the MCP toolset exposes evaluation,
use `browser_evaluate` to issue `fetch` from the page context.

Use shell `curl` only for unauthenticated health checks like `_preflight`.

## Reproducibility

One retry is mandatory before a finding is real:

1. Reset only the local page state needed for the step.
2. Re-run the same action sequence.
3. Capture fresh evidence.
4. Confirm the same expected-vs-actual mismatch.

If it fails once and passes on retry, record it as discarded-as-flaky in local
notes but do not include it as an actionable PR finding unless the user asks.

## Theme Toggle

To exercise dark/light variants of a scene, patch the authenticated user's
`theme_mode` via the API and reload. This is the same path the in-app theme
switcher uses and is the only reliable lever:

```js
// via mcp__playwright__browser_evaluate, in the authenticated page context
;async () => {
  const csrf = document.cookie.match(/csrftoken=([^;]+)/)?.[1]
  const r = await fetch('/api/users/@me/', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
    body: JSON.stringify({ theme_mode: 'dark' }), // or 'light' / 'system'
  })
  return { status: r.status, theme_mode: (await r.json()).theme_mode }
}
```

Then `browser_navigate` to the target route (a navigation reloads kea state).
Verify the toggle took effect by reading the computed background color, not
DOM attributes: PostHog does not set a `dark` class, `data-theme`, or
`data-color-mode` on `<html>` - the kea state drives CSS variables directly.

```js
;() => getComputedStyle(document.body).backgroundColor
// dark: ~rgb(19, 19, 22); light: ~rgb(243, 244, 240)
```

Do not try:

- `document.documentElement.classList.add('dark')` - themeLogic does not read it.
- `data-theme` / `data-color-mode` attributes - not consulted.
- `window.getKeaContext()` - not exposed in production builds.
- `emulateMedia({colorScheme:'dark'})` alone - only effective if the user's
  `theme_mode === 'system'`, and the seed user defaults to `null` / `'light'`.

Restore the original `theme_mode` (usually `'light'`) at the end of the run so
the dev environment is left as found.

## Seeding Test Data

A PR that adds "show counts of X" / "filter by Y" / "highlight rows when Z"
behavior often depends on data shapes that do not exist in a fresh local
stack. Empty states render fine, but the in-diff behavior never triggers.
Seed the minimum data needed to exercise the change before declaring
coverage, otherwise the run is a coverage gap, not a PASS.

Two backing stores:

- **Postgres** for app models (surveys, dashboards, cohorts, data warehouse
  sources, feature flags, organizations, etc.). Drive the Django ORM through
  a shell so model invariants stay intact:

  ```bash
  flox activate -- bash -c "uv run python manage.py shell <<'PY'
  from posthog.models import Team
  team = Team.objects.first()
  # create the minimum rows needed to exercise the diff
  PY"
  ```

- **ClickHouse** for events, person properties, session recordings, LLM
  spans, etc. Prefer the existing factory utilities under `posthog/test/` and
  `posthog/clickhouse/`; only drop to raw `INSERT INTO ... VALUES (...)` when
  no factory covers the shape you need.

Discipline:

- Seed the smallest possible set; do not bulk-load production-like volumes.
- Tag seeded rows with a recognizable marker (name prefix, fixed
  description, etc.) so you can identify and recover them later if needed.
- Reload the affected scene after seeding and assert the UI now reflects
  the data shape you set up.
- Note the seeding step in `run-notes.md` and in the PR comment's "What was
  tested" row so reviewers know what prerequisites were created.
- Do not delete the seeded rows at end of run by default; leave them for
  debugging. Clean up only if the user asked for it.

## Feature Flag Override

If the PR's behavior is gated behind a feature flag that is not enabled for
the seed user's project, the new UI stays hidden and the QA loop never
exercises it. Override the flag from the browser console via Playwright
MCP - no backend changes needed:

```js
// Enable a boolean flag
posthog.featureFlags.overrideFeatureFlags({ flags: { 'my-flag-key': true } })

// Set a multivariate flag to a specific variant
posthog.featureFlags.overrideFeatureFlags({ flags: { 'my-flag-key': 'variant-name' } })

// Clear all overrides
posthog.featureFlags.overrideFeatureFlags(false)
```

Issue these via `mcp__playwright__browser_evaluate` in the authenticated
page context, then navigate to the target route (a navigation reloads the
flag-driven render). Verify by snapshotting the page and confirming the
gated UI is now present.

At end of the QA loop, call `overrideFeatureFlags(false)` to clear the
override so the dev environment is left as found. Note the override step in
`run-notes.md` and surface it in the PR comment so reviewers know the test
ran with non-default flag state.

## Evidence Naming

Use stable, readable names:

```text
.qa-runtime/runs/<run-id>/001-login.png
.qa-runtime/runs/<run-id>/010-dashboard-load.png
.qa-runtime/runs/<run-id>/011-save-click-failure.png
.qa-runtime/runs/<run-id>/runtime-qa.gif
.qa-runtime/runs/<run-id>/console-errors.json
```

After a browser or visual test captures two or more screenshots, assemble the
ordered screenshots into `runtime-qa.gif` by default when `ffmpeg` or another
existing local GIF tool is available. This follows the same evidence pattern as
the demo-reel browser tier: screenshots stitched into a slow GIF. Use slow
frames, about 1.5-2 seconds each, and preserve the original PNGs.

Prefer the PostHog workspace's existing browser tooling for screenshots: capture
frames through Playwright MCP or the repo's existing `@playwright/test`
dependency. Do not add screenshot or GIF packages to `package.json`.

For stitching, prefer `ffmpeg` when available. Do not blindly include every PNG
in the run directory: choose 2-5 meaningful same-size key frames. Full-page
screenshots with different heights can make GIFs look stretched or huge. Copy or
symlink the selected frames into a temporary frame sequence first:

```bash
mkdir -p /tmp/qa-runtime-gif-<run-id>
ln -sf "$PWD/.qa-runtime/runs/<run-id>/003-state-a.png" /tmp/qa-runtime-gif-<run-id>/frame-001.png
ln -sf "$PWD/.qa-runtime/runs/<run-id>/011-state-b.png" /tmp/qa-runtime-gif-<run-id>/frame-002.png
ln -sf "$PWD/.qa-runtime/runs/<run-id>/014-state-c.png" /tmp/qa-runtime-gif-<run-id>/frame-003.png

ffmpeg -y -framerate 0.5 \
  -i "/tmp/qa-runtime-gif-<run-id>/frame-%03d.png" \
  -vf "scale=900:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5" \
  -loop 0 \
  ".qa-runtime/runs/<run-id>/runtime-qa.gif"
```

This command was verified against real `.qa-runtime` screenshots and produced a
small readable GIF (about 226 KB for three 1200x942 frames). If `ffmpeg` is not
available but another local GIF tool is, use that. If no GIF tool is already
available, skip the GIF and keep the screenshots as the evidence.

Keep paths relative in PR comments. Upload the bundle as a secret gist if the
comment would be too long.
