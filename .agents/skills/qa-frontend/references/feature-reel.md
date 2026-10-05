# Feature reel

A feature reel is a short animated WebP of one UI flow, for a PR description.
Use it when one still cannot show the change, for example a menu that opens on right-click, or a flow across two screens.
When one still can show the change, take the still instead (see "Screenshots" in `/writing-pr-descriptions`).

The reel is made from Storybook stills, not from a screen recording.
The camera zooms to the target of each step, a cursor glides there and clicks, and the next state fades in.
The motion is a pure function of the stills, so it is the same on every run, and the reel stays sharp on high-density screens.
The scripts need only the repo's Playwright and Pillow. Do not install ffmpeg or other packages for this mode.

Run every command below from the root of the PostHog checkout.

## 1. Start Storybook

Reuse a Storybook that runs. Otherwise, start one with `pnpm storybook` (port 6006).
Story ids are in `http://localhost:6006/index.json`.
On a cold dev server the first load of a story can take minutes, because Vite compiles each lazy chunk on its first request.
`reel-capture.mjs` waits up to five minutes for it.

## 2. Write the shot list

Start from a story that shows the first state of the flow, usually a story without a `play` function.
When no story shows that state, write a scratch story and keep it out of the commit.

Write each step of the flow as one entry in `steps`.
The `play` function of the story that shows the end state is often the best source: one `userEvent` or `fireEvent` call becomes one step.
The reel drives the steps itself, because a `play` function cannot be paused between its calls.

```json
{
  "url": "http://localhost:6006/iframe.html?id=scenes-app-project-homepage-today--home&viewMode=story",
  "viewport": { "width": 1280, "height": 800 },
  "steps": [
    { "caption": "Open Spaces", "action": "click", "target": { "label": "Spaces" } },
    {
      "caption": "Right-click a session",
      "action": "rightclick",
      "target": { "within": "[data-attr=\"today-recent-session\"]", "text": "Add a retry to the billing webhook" },
      "at": { "x": 40, "y": 14 },
      "waitFor": { "within": "[role=\"menu\"]", "text": "Open in new tab" },
      "focus": { "selector": "[role=\"menu\"]" }
    }
  ],
  "finalCaption": "Same actions as the hover card"
}
```

| Field             | Meaning                                                                                                                                                                                     |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `url`             | The iframe URL of the story: `http://localhost:6006/iframe.html?id=<story-id>&viewMode=story`                                                                                               |
| `viewport`        | Size in CSS pixels. The default is 1280×800                                                                                                                                                 |
| `steps[].caption` | Text on screen while the cursor moves to the target                                                                                                                                         |
| `steps[].action`  | `click`, `rightclick` or `hover`                                                                                                                                                            |
| `steps[].target`  | `{ "label": … }` (accessible name), `{ "text": … }` (exact text), `{ "text": …, "within": "<css>" }` (the `<css>` element that holds the text, such as a row), or `{ "selector": "<css>" }` |
| `steps[].at`      | Optional point in CSS pixels from the top-left corner of the target. The default is the center                                                                                              |
| `steps[].waitFor` | Optional target that must show after the action                                                                                                                                             |
| `steps[].focus`   | Optional target that the last step shows, such as a menu. The camera frames it in the final shot. Earlier steps ignore it                                                                   |
| `finalCaption`    | Text on screen at the end                                                                                                                                                                   |

Keep a reel to two to four steps. Each step adds about 1.4 seconds.
Captions are user-facing copy, so `/writing-user-facing-copy` applies: sentence case, a few words, no em dashes.

## 3. Capture, render and encode

```bash
RUN_DIR=".qa-frontend/runs/reel-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RUN_DIR"
# write the shot list to "$RUN_DIR/shot-list.json"
node "<skill_dir>/scripts/reel-capture.mjs" "$RUN_DIR/shot-list.json" "$RUN_DIR/capture"
node "<skill_dir>/scripts/reel-render.mjs" "$RUN_DIR/capture" "$RUN_DIR/frames"
uv run python "<skill_dir>/scripts/annotate-evidence.py" animate \
  --frames-dir "$RUN_DIR/frames" --max-width 1920 \
  --output "$RUN_DIR/feature-reel.webp"
```

Read the stills in `capture/` before you render. They are the whole content of the reel: a spinner, an empty state or a wrong row in a still is also in the reel. Fix the shot list or the story, then capture again.

Before you share the reel, read some frames from `frames/`: the first frame, one frame at each click, and the last frame.
Each step must show its cause: the cursor reaches the control before the next state fades in.
A two-step reel is about 3 MB and a three-step reel about 5 MB. The upload limit is 10 MB.

## 4. Add it to the PR

The upload gate in `references/safety-rules.md` applies: show the developer the reel and get approval before the upload.
Storybook renders mock data, but a scratch story or a caption can still carry names that must not be public.

```bash
# --yes only after the developer approves this exact file
hogli pr:upload-image --yes --alt "<what the flow shows>" "$RUN_DIR/feature-reel.webp"
```

Paste the markdown line that the command prints as the "after" of the change. For the "before", follow "Screenshots" in `/writing-pr-descriptions`.
