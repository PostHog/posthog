# Snapshots and visual review

In CI, `common/storybook/.storybook/test-runner.ts` loads each story in Playwright and takes a light and a dark snapshot.
Visual review compares each snapshot with its baseline and asks a person to approve any change.
A story that renders two different pictures for the same code blocks unrelated PRs, so most of this file is about making the picture the same on every run.

## Shard scheduling

CI balances story files across shards using measured durations in `storybook-timings.json`.
For new files, the sequencer estimates duration from the built index’s runnable story count and the median measured duration per story.
Without an index or comparable measured stories, it uses the median file duration instead.
The estimate changes scheduling only; every selected file still runs.

## `testOptions`

Set them in `parameters.testOptions` on the meta or on a story. A story's keys merge with the meta's.

### Waiting

| Key                         | Default                | What it does                                                                                                               |
| --------------------------- | ---------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `waitForSceneReady`         | `true`                 | Replaces the one-second settle delay with the scene readiness signal. Requires all asynchronous content to register holds. |
| `waitForLoadersToDisappear` | `true`                 | Waits until no loader shows, for 5 seconds (10 for dashboard and Max stories). See the loader list below.                  |
| `waitForSelector`           | none                   | Waits until the selector matches. An array waits for every selector. `'iframe.X >>> .inner'` waits inside an iframe.       |
| `waitForSelectorTimeout`    | the Playwright timeout | The timeout for `waitForSelector`, in milliseconds.                                                                        |
| `allowImagesWithoutWidth`   | `false`                | Skips the wait for every image to load. Use it for a story that shows a broken image on purpose.                           |
| `skipIframeWait`            | `false`                | Skips the wait for iframes and for network idle. Use it for an external iframe or background polling.                      |
| `jestTimeout`               | 60 seconds             | The time the whole story may take. A slow story is usually a bug, so raise this only with a reason.                        |

The runner counts these as loaders: `.Spinner`, `.quill-spinner`, `.LemonSkeleton`, `.LemonTableLoader`, `.Toastify__toast`, `[aria-busy="true"]`, `.SessionRecordingPlayer--buffering`, `.Lettermark--unknown` and `[data-attr="loading-bar"]`.

- A toast counts as a loader. A story that leaves a toast on screen times out.
- The loader wait holds until no loader on the page is visible. On a timeout, the error lists the loaders that still show.
- The loader wait runs again before each theme and before each capture, so a loader that starts late is waited for too.
- `waitForSelector` waits for existence. Pick an element that exists only after the async work is done, such as a row from the mocked data, not a container that renders before the data.
- For Monaco, wait for `.CodeEditor[data-editor-ready="true"]`. `.monaco-editor` also matches a root that Monaco adds to `<body>` before any editor mounts.
- A story that shows a loading state on purpose sets `waitForLoadersToDisappear: false` and waits for the loader with `waitForSelector`.

### Scene readiness

Scene readiness is enabled by default for every story. The runner does not add a fixed one-second settle delay.
Storybook reuses the product's scene-rendered tracker with a fresh instance per story. Its performance mark is `posthog:storybook:scene_rendered`; it does not enable boot analytics.
The runner waits for the current story's live readiness, since an earlier performance mark cannot tell whether more work started.

Suspense boundaries must use `SceneContentFallback`. For data, debounces, workers or imperative rendering, call `useSceneContentReady(ready)` from `scenes/useSceneContentReady` in the component that owns the work.
Start with `ready = false`, keep it false through the entire operation, and release it only when the final content has committed. Include dependent requests and deferred work; `!loading` is insufficient if loading starts after the initial render.
Every pending component holds readiness independently. Unmounting releases its hold. The app shell shares the story's tracker through its scene boundary.

A synchronous story needs no hold. An awaited `play` function still finishes before snapshotting.
The runner checks readiness before each theme and capture, retains image, font, loader and chart waits, and requires matching captures from the same ready version.
Missing signals, unresolved holds and unstable captures fail the story. If a story exposes loading work that is not tracked yet, register the missing hold. A temporary `testOptions.waitForSceneReady: false` restores the one-second delay for that story while the hold is repaired; it does not prove that the content is ready.

### Viewport and target

| Key                           | Default           | What it does                                                                                                                           |
| ----------------------------- | ----------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `viewport`                    | 1280 × 720        | The page size for the story.                                                                                                           |
| `viewportWidths`              | none              | One snapshot per preset width: `narrow` 568, `medium` 960, `wide` 1300, `superwide` 1920, all 720 tall. Timeouts scale with the count. |
| `snapshotTargetSelector`      | `#storybook-root` | Snapshots one element. Throws with `layout: 'fullscreen'`.                                                                             |
| `includeNavigationInSnapshot` | `false`           | For `layout: 'fullscreen'`, snapshots the viewport with the navigation instead of the scene alone.                                     |

`viewportWidths` takes one snapshot per width instead of the single default one, and names each `<story-id>--<width>--<theme>`:

```ts
export const MyStoryViewports: Story = createInsightStory(fixture, 'edit')
MyStoryViewports.parameters = {
  testOptions: { viewportWidths: ['medium', 'wide', 'superwide'] },
}
```

That gives `my-story-viewports--medium--light` and so on. `frontend/src/scenes/data-management/definition/DefinitionView.stories.tsx` is a working example.

### Themes, browsers and charts

| Key                | Default        | What it does                                                                                                           |
| ------------------ | -------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `skipLightMode`    | `false`        | No light snapshot. For a story pinned to dark.                                                                         |
| `skipDarkMode`     | `false`        | No dark snapshot. For a story that has no dark mode, or a known dark mode issue.                                       |
| `snapshotBrowsers` | `['chromium']` | Every browser runs the story, but only these take snapshots. `[]` runs the story and its play function and takes none. |
| `skipCanvasDraw`   | `false`        | Quill charts don't paint their canvas. Use it when the chart is not what the story shows and its paint flakes.         |

`snapshotBrowsers: []` suits a story whose picture can't be the same twice, but whose play function still tests something.

## What the runner does before each snapshot

You don't need to add waits for any of this. Knowing the order helps when a story times out or flakes.

1. Before the story renders, it sets the `storybook-test-runner` body class and the class for the story's layout. The body class turns off transitions and animations, pins the end state of a few animations, and hides scrollbars and decorative overlays. It also sets `content-visibility: visible` on every element, so offscreen content renders. A component opts in to more with `.storybook-test-runner &` in its styles. The story renders without scrollbars from the start, because Chromium can keep a scroll container's old height when scrollbars are hidden after layout.
2. It renders the story and waits for `load`. In CI it also waits for network idle.
3. It fires a resize and waits 300 ms for resize observers.
4. It runs the loader wait and `waitForSelector`.
5. For each theme, it sets `body[theme]` and the color scheme, then:
   - runs the loader wait again;
   - makes lazy images eager, waits until every image has loaded and decoded, and hides GIFs;
   - waits up to 8 seconds for iframes, plus 1 second;
   - scrolls the window and the scroll containers back to the top;
   - waits until the body size stops changing, for up to 3 seconds;
   - waits for scene readiness, or 1 more second for stories that explicitly disable it;
   - waits until no quill chart canvas is still painting.
6. It runs the loader wait again and captures the target. A component snapshot grows to include a popover or a tooltip that overflows the root.
7. It waits 100 ms, waits for chart paint, animations and loaders again, and captures again. It keeps the capture when two in a row match and no loader shows after the capture. After four unstable captures, a story using readiness fails. Other stories keep the last capture and log that the story is still changing.

Chromium runs with `--disable-partial-raster`. Without it, Chromium paints a partly changed tile again in place, and the anti-aliased edges in that tile can differ by a color level from run to run.

An iframe that loads `/embedded/` or `/shared/` gets a fixed placeholder page, so a shared dashboard or embed never loads the real app inside the story.

### Errors you may see

- **"rendered nothing"**: the snapshot target had no size. A component that positions itself, such as a modal or a popover, needs a decorator that gives it a sized box. Tag the story `test-skip` only when nothing can show it.
- **A timeout in the loader wait**: a spinner, a skeleton or a toast is still on screen. An unmocked request or a request that never answers is the usual cause.
- **A timeout in `waitForSelector`**: the selector never matched. Open the story locally with the same parameters and look for the element.
- **"Page stopped responding during …"**: the browser's main thread stopped answering, so the runner replaced the page. The retry and the later stories in the file run on the new page. In CI the message also shows as a warning in the run summary. It gives the CPU use of the browser processes, the JavaScript stack at the moment of the freeze, and whether stopping the page's script freed it. A freed page and a stack point to a script loop in the functions the stack names.
- **The story passes locally but fails in CI**: CI waits for network idle, its machine can use a different time zone, and it is slower. Look for polling, unmocked requests and time-of-day text.

## Baselines and visual review

- Baselines are hashes in `frontend/snapshots.yml`, one entry per `<story-id>[--<width>]--<theme>`, signed by visual review. The PNGs under `frontend/__snapshots__/` are not the baseline, and CI deletes them before each run.
- On a PR, CI runs only the stories that the diff can affect, in Chromium. Master and the merge queue run every story in Chromium. A nightly run on master renders every story in WebKit and Firefox, which take no snapshots and only catch stories that fail to render.
- The `run-ci-frontend` label runs every story on a PR. Use it to bring back a baseline for a story that the diff doesn't touch. The label takes effect on the next push or ready-for-review, not when you add it.
- Each changed snapshot shows up in the visual review run for the PR. A person approves it there, and finalizing the run commits the new hashes to the PR branch.
- A finalized run pushes a commit to the branch. In a stack, that forces a restack of every layer above it, so put the stories that change in the top layer.
- New and changed story files run up to three more times. A story that renders two different pictures across those runs fails as flaky before anyone approves it.
- A quarantined story still renders and is diffed, but it doesn't gate the PR. The Quarantine part of [the visual review README](../../../products/visual_review/README.md#current-state) says when to approve its new picture and how a quarantine ends.

## Make a story deterministic

[Deterministic stories](../../../docs/published/handbook/engineering/conventions/frontend-coding.md#deterministic-stories) in the frontend coding conventions lists each pattern that caused a real quarantine, and its fix.

Before you change a flaky story, compare the two pictures. The Flakiness tab in visual review lists the stories that flaked on master, and each run shows the baseline and the variant.
The region that differs usually names the cause: a strip at the bottom is a height race, an empty chart is a canvas reset, a shifted block is a width race, a skeleton is a late load.
Some flakes are a stale baseline. Compare with the git history of `frontend/snapshots.yml` first.
