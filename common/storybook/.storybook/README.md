# Storybook

## Adding new Tailwind classes

Tailwind is compiled by `@tailwindcss/postcss` on the initial build. Webpack's
HMR does not re-run PostCSS when story content changes, so a **newly used**
Tailwind utility (e.g. `bg-[rebeccapurple]`) won't appear until you restart
Storybook. Classes already present in the codebase hot-reload fine.

## Storybook visual regression tests

In CI, Playwright loads each story and takes a light and a dark snapshot by default. A story can skip either theme with `testOptions.skipLightMode` or `testOptions.skipDarkMode`.
Visual review compares them with the baselines in `frontend/snapshots.yml`. A changed picture is approved in the visual review run, and finalizing the run commits the new baselines to the PR.

`test-runner.ts` holds the capture logic and the `testOptions` story parameters. To keep a story from flaking, see [Deterministic stories](../../../docs/published/handbook/engineering/conventions/frontend-coding.md#deterministic-stories) in the frontend coding conventions.

Uses `"@storybook/test-runner"` see: https://storybook.js.org/docs/writing-tests/test-runner

## to run locally

before you do this... 🤷

in one terminal

```bash
hogli storybook
```

in another

```bash
pnpm exec playwright install
hogli storybook:test
```

## Viewport width variants

You can snapshot a story at multiple viewport widths
by setting `viewportWidths` in `testOptions`.
This produces one snapshot per width instead of the default single snapshot.

Available widths: `narrow` (568px), `medium` (960px), `wide` (1300px), `superwide` (1920px).

```ts
export const MyStoryViewports: Story = createInsightStory(fixture, 'edit')
MyStoryViewports.parameters = {
  testOptions: {
    viewportWidths: ['medium', 'wide', 'superwide'],
  },
}
```

Each width generates a separate snapshot file suffixed with the width name,
e.g. `my-story-viewports--medium--light.png`.

See `frontend/src/scenes/insights/stories/TrendsLine.stories.tsx` for a working example.
