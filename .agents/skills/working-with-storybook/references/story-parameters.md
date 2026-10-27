# Story parameters, decorators and tags

Every story runs inside six global decorators from `common/storybook/.storybook/preview.tsx`.
Each one reads a parameter, so a story sets state by setting the parameter, not by calling logic actions.

| Decorator                 | Parameter                    | What it does                                                                                    |
| ------------------------- | ---------------------------- | ----------------------------------------------------------------------------------------------- |
| `withKea`                 | none                         | Resets kea, the router and the mocks for each story, and resets `useAvailableFeatures` to none. |
| `withMockDate`            | `mockDate`                   | Pins the clock with `MockDate.set`, or resets it when the story sets none.                      |
| `withFeatureFlags`        | `featureFlags`               | Writes the flags into `window.POSTHOG_APP_CONTEXT.persisted_feature_flags`.                     |
| `withTheme`               | the `theme` global           | Sets `document.body[theme]` to `light` or `dark`.                                               |
| `withPageUrl`             | `pageUrl`                    | Pushes the URL to the kea router after the story mounts.                                        |
| `withChartCanvasSnapshot` | `testOptions.skipCanvasDraw` | Stops quill charts from painting their canvas, only in the test runner.                         |

A decorator in a story or meta, such as `mswDecorator`, sits inside all of them.
Before each render, Storybook also waits for the Inter and RoundHog fonts. Canvas charts measure text when they paint and never paint again after a font arrives.

## How story and meta parameters combine

Storybook merges a story's `parameters` into the meta's.
Plain objects merge key by key at every depth. Every other value, arrays included, replaces the meta's value.

- `testOptions` in a story keeps the meta's other `testOptions` keys.
- An array `featureFlags` in a story replaces the meta's list. Repeat the meta's flags in it.
- A record `featureFlags` merges with a meta record.

## `featureFlags`

```ts
parameters: { featureFlags: [FEATURE_FLAGS.MY_FLAG] }                        // each listed flag is on
parameters: { featureFlags: { [FEATURE_FLAGS.MY_EXPERIMENT]: 'test_b' } }    // pin a variant
parameters: { featureFlags: { 'bool-flag': true, 'my-experiment': 'test' } } // mix both
```

- The default is no flags, so every flag is off.
- `featureFlagLogic` reads the persisted flags on mount and keeps them under every later flag load, so a pinned variant survives the empty flag callback posthog-js fires on load.
- `STORYBOOK_FEATURE_FLAGS` from `lib/constants` is every flag except `TODAY_RAIL_NAV` and `INTERNAL_FEEDBACK_WIDGET`. The rail swaps the whole navigation, so a story opts in to it on its own. Use the constant for a scene story that shows the app with everything on.
- Never call `featureFlagLogic.actions.setFeatureFlags` from a story. It passes in jest, and in visual review posthog-js wipes it, so the snapshot shows the flag-off branch.

[setting-feature-flags-in-storybook](../../setting-feature-flags-in-storybook/SKILL.md) explains the failure in full. A component that reads flags from a different posthog-js instance, such as the toolbar, needs that instance's own override: `Toolbar.stories.tsx` calls `toolbarPosthogJS.featureFlags.overrideFeatureFlags` for this reason.

## `mockDate`

```ts
parameters: {
  mockDate: '2024-01-15'
} // also a timestamp or a Date
parameters: {
  mockDate: '2024-01-15 10:01:00'
}
```

- `Date.now()`, `new Date()` and dayjs read the pinned time. Timers still run on the real clock.
- Write the dates in mock data relative to the pinned date. A story that shows "3 days ago" from a real clock fails next week on every branch.
- Nothing pins the time zone. The browser uses the zone of the machine it runs on, so a time of day can render differently on your machine and in CI. Check it in the CI snapshot, or format it in UTC.

## `pageUrl`

```ts
parameters: {
  pageUrl: urls.insightNew()
}
```

- The router uses an in-memory history per story, so the browser URL never changes and stories don't leak routes into each other.
- A story that renders the whole app (`<App />` from `scenes/App`) needs `pageUrl` to pick the scene.
- `pageUrl` pushes in an effect, after the story's first render. A component that reads the URL during that first render sees the default route once, then the pushed one.

## `layout`

| Value                | Body class in the runner            | What the snapshot captures                                                                        |
| -------------------- | ----------------------------------- | ------------------------------------------------------------------------------------------------- |
| `'padded'` (default) | `storybook-test-runner--padded`     | `#storybook-root`, which shrink-wraps its content, with a transparent background                  |
| `'centered'`         | `storybook-test-runner--centered`   | `#storybook-root`                                                                                 |
| `'fullscreen'`       | `storybook-test-runner--fullscreen` | The scene: the last of `body` and `main`, without navigation unless `includeNavigationInSnapshot` |

- In `padded`, content that measures its container when it mounts (Monaco, charts, React Flow) takes whatever width the root had. Wrap it in a fixed width such as `w-[42rem]`, not a `max-w-*`.
- In `fullscreen`, the app shell has `min-height: 100vh`. Content shorter than the viewport leaves a blank strip under it. Add a decorator that lets the shell hug its content when that matters.
- The `storybook-viewport-layout` body class keeps the app shell at the viewport height instead. `TerminalScene.stories.tsx` uses it for a docked panel that resizes.
- `testOptions.snapshotTargetSelector` throws with `fullscreen`. Use `padded` to snapshot one element.

## Theme

- The `theme` global sets `body[theme]`. The toolbar in Storybook switches it, and a URL picks it with `&globals=theme:dark`.
- A story can set `globals: { theme: 'dark' }`, but the runner still takes a light and a dark snapshot and sets the theme for each one. A story pinned to dark sets `testOptions.skipLightMode: true` too.
- `themeLogic.isDarkModeOn` follows the runner's theme. A component that reads it can lag one render behind the attribute. Read `document.body.getAttribute('theme')` when a snapshot shows the wrong theme.

## `viewMode`, `docs` and other Storybook parameters

- Many stories set `viewMode: 'story'`. Nothing in the runner reads it, and it changes nothing that a snapshot shows.
- `docs`, `controls`, `actions` and `options` are standard Storybook parameters for the Storybook UI. The runner ignores them.
- `parameters.msw.mocks` works only with `mswDecorator` on the story or meta. No global decorator reads it. See [mocking-data.md](mocking-data.md).
- A parameter that only one file uses, such as `narrow`, `width` or `tab`, is read by that file's own `render` or `beforeEach`. Read the file before you copy one.

## Story functions: `render`, `play`, `beforeEach`, `loaders`

- `render(args, context)` builds the story. `context.parameters` holds the merged parameters, so a meta `render` can read a story parameter.
- `play` runs after the render, in the browser, and the runner waits for it before the snapshot. In a play function, import `within` and `waitFor` from `@testing-library/dom`, which has a 15 second async timeout here. `storybook/test` has its own shorter default.
- `beforeEach` runs before each render and can return a cleanup function. Use it for setup that must be undone, such as a body class.
- On a retry the runner remounts the story and runs `play` again. A play function that fails or doesn't settle within 30 seconds fails the story.

## Tags

| Tag                  | Effect                                                                                                                                  |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `'test-skip'`        | The runner skips the story: no snapshot. Say why in a comment, for example a canvas the runner can't capture.                           |
| `'test-skip-webkit'` | The WebKit run skips the story. CI sets `STORYBOOK_SKIP_TAGS=test-skip,test-skip-<browser>`. `'test-skip-chromium'` works the same way. |
| `'!test'`            | Removes Storybook's implicit `test` tag, so the runner never collects the story. Use it for a story that needs a live service.          |
| `'autodocs'`         | Storybook generates a docs page for the file. Only tagged files get one.                                                                |

Put tags on the meta (`tags: ['test-skip']`) to cover every story in the file, or on one story.
A skipped story has no baseline, so visual review can't catch a regression in it. Fix the cause when you can, and skip only what the runner can't capture.
