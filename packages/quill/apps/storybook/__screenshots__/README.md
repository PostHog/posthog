# Quill story screenshots

Visual regression baseline for the quill refactor (Tailwind → CSS/BEM migration).

## Capture baseline

```sh
# one-off: build static + run capture
pnpm --filter @posthog/quill-storybook build-storybook
cd packages/quill/apps/storybook/storybook-static
python3 -m http.server 6006 --bind 127.0.0.1 &
cd ../..
CHROME_EXECUTABLE_PATH="$HOME/Library/Caches/ms-playwright/chromium-1124/chrome-mac/Chromium.app/Contents/MacOS/Chromium" \
    node apps/storybook/scripts/capture-screenshots.mjs
# stop server
lsof -ti:6006 | xargs kill
```

Outputs: `baseline/light/<story-id>.png`, `baseline/dark/<story-id>.png`, `baseline/manifest.json` (177 stories × 2 themes = 354 PNGs, ~6 MB).

## Regression check after refactor

```sh
# 1. rebuild storybook from the refactored branch
pnpm --filter @posthog/quill-storybook build-storybook
# 2. serve again on :6006 (same as above)
# 3. run compare: captures into candidate/ and diffs vs baseline/
CHROME_EXECUTABLE_PATH="..." node apps/storybook/scripts/compare-screenshots.mjs
```

Report lands in `__screenshots__/diff-report.json`. Exit code non-zero if any story diffs.

## Notes

- `SB_OUT_DIR=/abs/path` redirects capture output — used by compare-screenshots.mjs to target `candidate/`.
- `SB_CONCURRENCY=N` tunes parallel browser contexts (default 4).
- `SB_URL=http://...` overrides the static server URL.
- Viewport is fixed at 1280×800, `deviceScaleFactor: 1`, fullpage, animations disabled, caret hidden — keeps diffs deterministic.
- Both themes captured because many variants (popover bg, ring colors, fill-selected) only show regressions in one mode.
- `pixelmatch` + `pngjs` give pixel-accurate diffs. Without them, compare falls back to byte-equal (noisier but still catches most regressions).
