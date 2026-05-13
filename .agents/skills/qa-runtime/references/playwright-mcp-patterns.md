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
