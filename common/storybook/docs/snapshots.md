# Snapshots and visual review

In CI, `common/storybook/.storybook/test-runner.ts` loads each story in Playwright and takes a light and a dark snapshot.
Visual review compares each snapshot with its baseline and asks a person to approve any change.
A story that renders two different pictures for the same code blocks unrelated PRs, so most of this file is about making the picture the same on every run.

## `testOptions`

Set them in `parameters.testOptions` on the meta or on a story. A story's keys merge with the meta's.

### Waiting

| Key                         | Default                | What it does                                                                                                         |
| --------------------------- | ---------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `waitForLoadersToDisappear` | `true`                 | Waits until no loader shows, for 5 seconds (10 for dashboard and Max stories). See the loader list below.            |
| `waitForSelector`           | none                   | Waits until the selector matches. An array waits for every selector. `'iframe.X >>> .inner'` waits inside an iframe. |
| `waitForSelectorTimeout`    | the Playwright timeout | The timeout for `waitForSelector`, in milliseconds.                                                                  |
| `allowImagesWithoutWidth`   | `false`                | Skips the wait for every image to load. Use it for a story that shows a broken image on purpose.                     |
| `skipIframeWait`            | `false`                | Skips the wait for iframes and for network idle. Use it for an external iframe or background polling.                |
| `jestTimeout`               | 60 seconds             | The time the whole story may take. A slow story is usually a bug, so raise this only with a reason.                  |

The runner counts these as loaders: `.Spinner`, `.quill-spinner`, `.LemonSkeleton`, `.LemonTableLoader`, `.Toastify__toast`, `[aria-busy="true"]`, `.SessionRecordingPlayer--buffering`, `.Lettermark--unknown` and `[data-attr="loading-bar"]`.

- A toast counts as a loader. A story that leaves a toast on screen times out.
- The loader wait checks only the first element that matches. When a story shows more than one loader, wait for content that renders after the last one.
- `waitForSelector` waits for existence. Pick an element that exists only after the async work is done, such as a row from the mocked data, not a container that renders before the data.
- For Monaco, wait for `.CodeEditor[data-editor-ready="true"]`. `.monaco-editor` also matches a root that Monaco adds to `<body>` before any editor mounts.
- A story that shows a loading state on purpose sets `waitForLoadersToDisappear: false` and waits for the loader with `waitForSelector`.

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

1. It loads the story and waits for `load`. In CI it also waits for network idle.
2. The `storybook-test-runner` body class turns off transitions and animations, pins the end state of a few animations, and hides scrollbars and decorative overlays. A component opts in to more with `.storybook-test-runner &` in its styles.
3. It makes hidden `content-visibility` content visible, fires a resize, and waits 300 ms for resize observers.
4. It runs the loader wait and `waitForSelector`.
5. For each theme, it sets `body[theme]` and the color scheme, then:
   - makes lazy images eager, waits until every image has loaded and decoded, and hides GIFs;
   - waits up to 8 seconds for iframes, plus 1 second;
   - scrolls the window and the scroll containers back to the top;
   - waits until the body size stops changing, for up to 3 seconds;
   - waits 1 more second;
   - waits until no quill chart canvas is still painting.
6. It captures the target. A component snapshot grows to include a popover or a tooltip that overflows the root.

An iframe that loads `/embedded/` or `/shared/` gets a fixed placeholder page, so a shared dashboard or embed never loads the real app inside the story.

### Errors you may see

- **"rendered nothing"**: the snapshot target had no size. A component that positions itself, such as a modal or a popover, needs a decorator that gives it a sized box. Tag the story `test-skip` only when nothing can show it.
- **A timeout in the loader wait**: a spinner, a skeleton or a toast is still on screen. An unmocked request or a request that never answers is the usual cause.
- **A timeout in `waitForSelector`**: the selector never matched. Open the story locally with the same parameters and look for the element.
- **The story passes locally but fails in CI**: CI waits for network idle, its machine can use a different time zone, and it is slower. Look for polling, unmocked requests and time-of-day text.

## Baselines and visual review

- Baselines are hashes in `frontend/snapshots.yml`, one entry per `<story-id>[--<width>]--<theme>`, signed by visual review. The PNGs under `frontend/__snapshots__/` are not the baseline, and CI deletes them before each run.
- On a PR, CI runs only the stories that the diff can affect, in Chromium. Master and the merge queue run every story, in WebKit too.
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
