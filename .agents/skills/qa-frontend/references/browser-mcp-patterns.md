# Browser MCP Patterns

Use browser MCP/tooling as the browser lens. Prefer user-visible assertions over implementation assertions. Playwright MCP is the known-good concrete example in this repo; Chrome DevTools MCP or another browser MCP is fine when it exposes the same primitives: navigate, interact, evaluate JavaScript in page context, capture screenshots, and inspect console/network signals.

## MCP Availability

This skill requires browser MCP/tooling. If no browser MCP tools are available in the current session, stop and ask before configuring anything: "I do not see a browser MCP tool in this session. Do you want me to configure one for this agent environment, or would you prefer to set it up yourself? If I configure it, should it be local to this repo/workspace, user-wide, or another scope supported by your client?"

Prefer the narrowest non-committed scope that works for the user's current client. Never silently edit checked-in repo MCP config such as `.mcp.json`, use a project/repo-committed scope, or commit MCP config just to run QA. After adding a browser MCP server, tell the user they may need to reconnect/restart the agent session before rerunning `qa-frontend`.

Client-specific examples are guidance, not universal instructions:

- Claude Code local scope: `claude mcp add --scope local playwright -- npx -y @playwright/mcp@0.0.75`
- Chrome DevTools MCP: the server is commonly named `chrome-devtools`, which maps to a `mcp__chrome-devtools__*` tool namespace in clients that preserve server names. Use the browser MCP setup already preferred by the current client or repo guidance; keep it local/user-scoped, not committed.
- Cursor or other clients: use that client's local or user MCP settings, not repo-committed config.
- Codex: use available browser tooling if exposed; otherwise ask the user how they want browser automation configured for their Codex environment.

## Browser Flow Skeleton

The names below use Playwright MCP as examples. With Chrome DevTools MCP or another browser MCP, use the equivalent navigate, snapshot/DOM, evaluate, screenshot, console, and network tools exposed by that server.

1. Navigate to the target URL, for example `mcp__playwright__browser_navigate`.
2. Read the action response. Navigation often includes an automatic snapshot.
3. Call a snapshot/DOM inspection tool when the page state is unclear, for example `mcp__playwright__browser_snapshot`.
4. Interact by role, text, or accessible snapshot reference. Prefer visible controls over CSS selectors.
5. After each meaningful action, assert on UI state: changed text, toast, table row, modal state, URL change, or other visible result.
6. Capture a screenshot under `.qa-frontend/runs/<run-id>/`.
7. Read error-level console messages and network failures for the page.

## Locked Browser Profile

If browser MCP/tooling reports that the browser profile is already in use, treat it as an infrastructure blocker, not a QA result.

1. Prefer the MCP/browser option that starts a fresh isolated profile, when one is available.
2. If a stale local browser process is holding the profile, ask the user before killing processes or clearing profile locks.
3. After recovery, re-open the target route and repeat the affected action from scratch.
4. If the lock cannot be resolved, record a coverage gap with the exact browser error and do not claim the route was tested.

Do not delete browser profile data or close the user's visible browser windows without explicit approval.

## Browser Session Cleanup

At the end of the QA run, close the browser automation session if the browser MCP/tooling exposes a close-page, close-context, close-browser, or end-session action. This prevents stale Chromium sessions from holding profile locks or confusing later QA attempts.

Do not close the user's visible browser windows. If a stale headless Chromium process from a previous agent blocks the run and no MCP close action is available, ask before killing it, and target only agent-started browser processes.

Useful command-line markers for agent-started browser sessions include `ms-playwright`, `mcp-chrome-`, `remote-debugging-pipe`, and `playwright-mcp`. Visible user browsers usually use the normal browser profile instead. If you inspect processes, use these markers to explain exactly what you plan to terminate before asking for approval.

## Snapshot Use

Start with the default snapshot. Deepen or scroll only when:

- The target element is likely below the fold.
- A collapsed panel hides the changed feature.
- The default snapshot has only loading or shell content.

Do not declare an element absent until you have checked the plausible scroll or tab state.

## Console And Network Signals

Collect a baseline console snapshot after initial page load, then compare after the changed action. Treat a new error as relevant only if it appears after the target interaction or clearly belongs to the exercised endpoint.

Ignore known pre-existing third-party noise when it was present before the action and does not affect the changed flow.

**Distinguish local-stack noise from PR-introduced errors.** Before scoring any console output, check process-specific dev state through phrocs MCP:

- `mcp__phrocs__get_process_status(process="backend")`
- `mcp__phrocs__get_process_status(process="frontend")`
- The process implied by the error, for example `capture`, `feature-flags`, `temporal-worker`, or `mcp`

Do not rely on all-process status during startup; process-specific calls can work while all-process status is still flaky. Common patterns to recognize and discount, _only_ when the failing process explains them:

- 502s from `capture`, `capture-ai`, `capture-replay` endpoints when those processes are `stopped` or `crashed`
- 500s from invocations / hog flow paths when the `posthog-node` (CDP) or `temporal-worker` process is down
- `Failed to load resource: 404` on `/decide`, remote-config, or feature-flag endpoints when `feature-flags` or `flags-consumer` is stopped
- CORS or font-CDN failures from third-party scripts in dev

Errors are in-scope (worth flagging) when they touch a code path the PR actually changed, regardless of when they fire - including on initial mount, before any user interaction. A scene that throws on first render or fetches a wrong endpoint on load is a real bug, not pre-existing noise. Errors at load time on the affected surface deserve the same scrutiny as errors that follow a click or form submit.

Errors are out-of-scope (worth discounting) when they are explained by a stopped local process from the list above, or by third-party scripts unrelated to the diff.

When you discount errors, call out the triage explicitly in run notes and in the PR comment ("All console errors traced to capture process being stopped on this machine; no new errors introduced by this PR"). Silently swallowing console output erodes trust in the report.

## Page Context Helpers

Use authenticated `fetch` from the browser page context only to set up or inspect frontend state that the visible flow needs. Cookies and CSRF state come from the browser session. Do not turn this into a standalone backend test plan.

Use shell `curl` only for unauthenticated health checks such as `_health`.

## Reproducibility

One retry is mandatory before a finding is real:

1. Reset only the local page state needed for the step.
2. Re-run the same action sequence.
3. Capture fresh evidence.
4. Confirm the same expected-vs-actual mismatch.

If it fails once and passes on retry, re-run it once more when that is cheap. Do not report it as a confirmed finding, but do not hide it either: give it its own coverage row with the result `INTERMITTENT`, keep the first failure's evidence in the run directory, and describe what was observed in run notes. A real race that reads as a clean PASS erodes more trust than an honest intermittent row.

## Theme Toggle

To exercise dark/light variants of a scene, patch the authenticated user's `theme_mode` from the page context and reload. This is the same path the in-app theme switcher uses and is the only reliable lever:

```js
// via the browser MCP evaluate tool, in the authenticated page context
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

Then navigate to the target route (a navigation reloads kea state). `<html>` carries a server-rendered `data-boot-theme` attribute (check `document.documentElement.dataset.bootTheme` for the boot state), but a runtime toggle does not update it - verify the toggle took effect by reading the computed background color: the kea state drives CSS variables directly, and PostHog sets no runtime `dark` class or `data-theme`/`data-color-mode` attribute.

```js
;() => getComputedStyle(document.body).backgroundColor
// dark: ~rgb(19, 19, 22); light: ~rgb(243, 244, 240)
```

Do not try:

- `document.documentElement.classList.add('dark')` - themeLogic does not read it.
- `data-theme` / `data-color-mode` attributes - not consulted.
- `window.getKeaContext()` - not exposed in production builds.
- `emulateMedia({colorScheme:'dark'})` alone - only effective if the user's `theme_mode === 'system'`, and the seed user defaults to `null` / `'light'`.

Restore the original `theme_mode` (usually `'light'`) at the end of the run so the dev environment is left as found.

## Seeding Test Data

A PR that adds "show counts of X" / "filter by Y" / "highlight rows when Z" behavior often depends on data shapes that do not exist in a fresh local stack. Empty states render fine, but the in-diff behavior never triggers. Seed the minimum data needed to exercise the change before declaring coverage, otherwise the run is a coverage gap, not a PASS.

Two backing stores:

- **Postgres** for app models (surveys, dashboards, cohorts, data warehouse sources, feature flags, organizations, etc.). Drive the Django ORM through a shell so model invariants stay intact:

  ```bash
  flox activate -- bash -c "uv run python manage.py shell <<'PY'
  from posthog.models import Team
  team = Team.objects.first()
  # create the minimum rows needed to exercise the diff
  PY"
  ```

- **ClickHouse** for events, person properties, session recordings, LLM spans, etc. Prefer the existing factory utilities under `posthog/test/` and `posthog/clickhouse/`; only drop to raw `INSERT INTO ... VALUES (...)` when no factory covers the shape you need.

Discipline:

- Seed the smallest possible set; do not bulk-load production-like volumes.
- Tag seeded rows with a recognizable marker (name prefix, fixed description, etc.) so you can identify and recover them later if needed.
- Reload the affected scene after seeding and assert the UI now reflects the data shape you set up.
- Note the seeding step in `run-notes.md` and in the PR comment's "What was tested" row so reviewers know what prerequisites were created.
- Do not delete the seeded rows at end of run by default; leave them for debugging. Clean up only if the user asked for it.

## Feature Flag Override

If the PR's behavior is gated behind a feature flag that is not enabled for the seed user's project, the new UI stays hidden and the QA loop never exercises it. Override the flag from the authenticated browser page context - no backend changes needed:

```js
// Enable a boolean flag
posthog.featureFlags.overrideFeatureFlags({ flags: { 'my-flag-key': true } })

// Set a multivariate flag to a specific variant
posthog.featureFlags.overrideFeatureFlags({ flags: { 'my-flag-key': 'variant-name' } })

// Clear all overrides
posthog.featureFlags.overrideFeatureFlags(false)
```

Issue these via the active browser MCP evaluate tool in the authenticated page context, then navigate to the target route (a navigation reloads the flag-driven render). Verify by snapshotting the page and confirming the gated UI is now present.

At end of the QA loop, call `overrideFeatureFlags(false)` to clear the override so the dev environment is left as found. Note the override step in `run-notes.md` and surface it in the PR comment so reviewers know the test ran with non-default flag state.

## Evidence Naming

Use stable, readable names:

```text
.qa-frontend/runs/<run-id>/001-login.png
.qa-frontend/runs/<run-id>/011-save-click-failure.png
.qa-frontend/runs/<run-id>/011-save-click-failure.annotated.png
.qa-frontend/runs/<run-id>/frontend-qa.webp
.qa-frontend/runs/<run-id>/console-errors.json
```

Prefer the PostHog workspace's existing browser tooling for screenshots: capture frames through the active browser MCP/tooling or the repo's existing `@playwright/test` dependency. Do not add screenshot, image, or video packages to `package.json`.

## Annotating Evidence

Raw screenshots make the reviewer reconstruct what happened. Annotate the key frames so each one explains itself: a caption bar below the screenshot saying what the step did, a PASS/FAIL/INFO chip, and for findings a highlight box around the element that matters. `<skill_dir>/scripts/annotate-evidence.py` does both annotation and animation with the repo's existing Pillow dependency; run it with `uv run python` from a trusted checkout (for example the repo the skill directory lives in), never from the PR checkout - `uv run` resolves that tree's dependencies. Do not use `ffmpeg` or install anything for evidence processing.

To highlight the relevant region, grab the element's rect in CSS pixels through the browser MCP evaluate tool right after capturing the screenshot, along with the viewport width for HiDPI scaling:

```js
;() => {
  const el = document.querySelector('<selector for the element that matters>')
  const r = el.getBoundingClientRect()
  return { x: r.x, y: r.y, w: r.width, h: r.height, viewportWidth: window.innerWidth }
}
```

Then annotate the frame. Keep the raw PNG; write the annotated copy next to it:

```bash
uv run python "<skill_dir>/scripts/annotate-evidence.py" annotate \
  --input "$RUN_DIR/011-save-click-failure.png" \
  --caption "Clicked Save - no toast, no network call" \
  --step 3 --status fail \
  --highlight 840,220,320,88 --viewport-width 1280
```

`--highlight` is repeatable and optional; skip it when the whole frame is the story. Because the browser is driven through element references, no cursor is ever visible in screenshots - when a frame shows an interaction, add `--click X,Y` (the clicked element's center) to draw a cursor with a click ring so the reader sees where the action happened. Use `--click` for interactions and `--highlight` for result regions; both on the same element is redundant. Captions state what happened and what it means, not internal codenames.

## Demo Reel

After a browser or visual target captures two or more screenshots, assemble 2-5 annotated key frames into a slow animated WebP. WebP keeps full 24-bit color at a fraction of GIF size, and GitHub renders animated WebP inline in PR comments. Only include frames a reviewer needs to follow the flow - skipping dead time between meaningful moments is the point of a stitched reel. Every state change needs its cause on screen: before each frame where something appeared or changed, the previous frame must carry the `--click` marker on the control that caused it. A copy that just materializes with no visible click reads as confusion, not evidence - this applies to retries too, which are their own cause-and-effect pair. Give finding frames a little more screen time:

```bash
uv run python "<skill_dir>/scripts/annotate-evidence.py" animate \
  --frame "$RUN_DIR/003-state-a.annotated.png:1500" \
  --frame "$RUN_DIR/011-save-click-failure.annotated.png:2500" \
  --frame "$RUN_DIR/014-state-c.annotated.png:1500" \
  --output "$RUN_DIR/frontend-qa.webp"
```

The script caps width at 1200px, pads mixed-height frames instead of stretching them, and prints the output size. A 3-5 frame reel of 1200px UI screenshots lands well under 200 KB. Add `--gif <path>` only when a GIF fallback is explicitly needed; it is several times larger for the same frames.

Before uploading or embedding the reel, inspect it with the Read tool or by opening it. If text is not readable or the sequence is less clear than the stills, keep the annotated PNGs as the evidence instead.

## Recorded Demo Pass (default video output)

The WebP reel autoplays like a GIF and cannot be paused or scrubbed. A real video only earns its place when it shows what a human would see: smooth page transitions and a visible cursor moving to each control. Element-driven automation renders no cursor at all - not in screenshots and not in session recordings - so a raw recording of the QA loop is jumpy and hard to follow. Do not build videos by stitching still frames; that is just a pausable reel.

Run a **demo pass** by default after the QA loop settles: re-run the key flow once, with recording on and a visible cursor injected. Skip it only when `NO_VIDEO` was set, the browser tool cannot record video, or `ffmpeg` is missing - never silently: state the skip and its reason in run notes and the report's Setup section.

1. Start recording with the browser tool's native recording (`agent-browser record start "$RUN_DIR/demo.webm"` when agent-browser is available, or Playwright MCP video capture via `PLAYWRIGHT_MCP_SAVE_VIDEO=1280x720`, which exposes `browser_start_video` / `browser_stop_video` with chapter markers). If neither is available, ask before reconfiguring anything, then skip video mode rather than improvising.
2. Wait for the page to be usable again before acting. Starting a recording typically recreates the browser context, which reloads the page; on a cold dev server that reload can take a while. Poll for a marker element, not a fixed sleep. Everything recorded before the first action is lead-in to trim.
3. Inject `<skill_dir>/scripts/cursor-overlay.js` into the page with the browser tool's evaluate/eval - it draws a cursor that follows real mouse events, ripples on click, shows a caption bar, and exposes `window.__qaCursor`. It is visual-only (`pointer-events: none`) and must be re-injected after every navigation.
4. Script the whole flow as one continuous batch so there is no dead time between steps - gaps between separate tool calls all end up on film. Each step: set the caption, glide, ripple, click, brief settle. Captions narrate the same story as the annotated stills (step number, what is happening, pass/fail):

   ```js
   window.__qaCursor.caption('Step 2 · Clicking Duplicate on Question 1', 'info')
   const r = el.getBoundingClientRect()
   await window.__qaCursor.glide(r.x + r.width / 2, r.y + r.height / 2, 650)
   window.__qaCursor.ripple(r.x + r.width / 2, r.y + r.height / 2)
   el.click()
   ```

   If real input events are unreliable in the session (a known agent-browser daemon quirk), programmatic `el.click()` plus an explicit `ripple()` looks identical on film.

   The caption bar overlays the bottom edge of the page, and PostHog anchors toasts and some action buttons there. When a step's proof is a bottom-anchored element, clear the caption for that beat with `window.__qaCursor.caption(null)` and restore it afterwards, so the recording never covers the result it exists to show.

5. Stop recording, trim any lead-in, and transcode for universal playback:

   ```bash
   uv run python "<skill_dir>/scripts/annotate-evidence.py" video \
     --input "$RUN_DIR/demo.webm" \
     --output "$RUN_DIR/frontend-qa.mp4" \
     --trim-start <lead-in seconds>
   ```

   `--trim-start` uses ffmpeg output seeking, which decodes from the start and cuts frame-accurately. Never trim the WebM yourself with input seeking (`-ss`/`-sseof` before `-i`): screencast WebMs have very sparse keyframes, so input seeks snap far from the requested point and silently shift the whole window.

6. Verify the final video before sharing it - the agent cannot watch video, so render a frame contact sheet and read it like the reel inspection:

   ```bash
   ffmpeg -y -i "$RUN_DIR/frontend-qa.mp4" \
     -vf "fps=1,scale=420:-1,tile=5x2" -frames:v 1 /tmp/qa-video-sheet.png
   # fps=1 with tile=5x2 covers 10 seconds; for longer clips raise the tile
   # (tile=5x4 for 20 s) or lower fps - the sheet must reach the final frame
   ```

   The sheet must show the caption bar present from the first seconds, every step's caption in order, motion between frames (no stretches of identical idle frames), and the final finding state held at the end. If it does not, fix the trim and re-check; do not share an unverified video.

Transcoding needs a local `ffmpeg`; if it is missing, keep the WebM and say so in run notes. A 15-second 1280px demo lands around 300 KB. Keep the MP4 under ~10 MB so it stays drag-droppable into a GitHub comment. Do not try to auto-embed video in an agent-posted comment: GitHub only renders a video player for files uploaded by hand through its web editor, and raw-hosted MP4 links are served as downloads, not playable video. Link the MP4 from the local report; in PR mode it may join the approved upload set via `hogli pr:upload-video` (a download link in the comment), and the developer can still drag the file into the comment editor for an inline player. The overlay uses only opaque brand colors, so it reads identically on light and dark themes.

Keep paths relative in PR comments. If the comment would be too long, summarize the evidence and rely on the approved uploaded files or the local report. Do not fall back to a secret gist.
