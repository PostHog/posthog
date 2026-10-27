---
name: working-with-storybook
description: >
  Runs, writes and debugs PostHog Storybook stories and their visual review snapshots.
  Use when you start Storybook to look at a change, write or change a `*.stories.tsx` file,
  mock API data, feature flags, the date, the URL or plan features for a story,
  pick a story `layout` or `testOptions`, or fix a story that times out, renders nothing or flakes in visual review.
  Covers `STORYBOOK_STORIES` for running a few stories, the global decorators and their parameters
  (`featureFlags`, `mockDate`, `pageUrl`, theme), MSW mocks (`mswDecorator`, `useStorybookMocks`),
  `useAvailableFeatures`, the app context every story starts with, every `testOptions` key,
  tags (`test-skip`, `test-skip-webkit`, `!test`, `autodocs`), what the test runner does before each snapshot,
  and how CI baselines and visual review work.
  Trigger terms: storybook, story, stories, pnpm storybook, STORYBOOK_STORIES, testOptions, waitForSelector,
  mswDecorator, mockDate, pageUrl, visual review, snapshot, baseline, flaky story.
---

# Working with Storybook

Storybook is where a UI change gets looked at before the stack runs, and where CI takes the light and dark snapshots that visual review compares.
The setup lives in `common/storybook/.storybook/`: `main.ts` (story globs, Vite), `preview.tsx` (global decorators and parameters), `test-runner.ts` (the snapshot runner), `decorators/`.

## Pick the reference

| You want to                                                                                         | Read                                                                                   |
| --------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Start Storybook for a few stories, open a story by URL, take screenshots, run the test runner       | [references/running-storybook.md](references/running-storybook.md)                     |
| Set flags, the date, the URL, the layout or the theme of a story, or tag it                         | [references/story-parameters.md](references/story-parameters.md)                       |
| Mock API responses, plan features, the current user, team or preflight                              | [references/mocking-data.md](references/mocking-data.md)                               |
| Pick `testOptions`, understand what the runner waits for, fix a timeout, an empty render or a flake | [references/snapshots-and-visual-review.md](references/snapshots-and-visual-review.md) |

Feature flags have their own skill, [setting-feature-flags-in-storybook](../setting-feature-flags-in-storybook/SKILL.md), because the wrong way passes in jest and fails only in visual review.

## Rules that apply to every story

- **Run only the stories you need.** Set `STORYBOOK_STORIES=<dir or story file>` before `pnpm storybook`. Never edit the `stories` list in `main.ts` to narrow it.
- **Set state through parameters, not through logic actions.** `featureFlags`, `mockDate` and `pageUrl` are parameters that global decorators apply before the story renders. An action dispatched from a story can run after the snapshot, or be undone by a load that finishes later.
- **Mock every request the story makes.** Use `mswDecorator` or `useStorybookMocks`. An unmocked request goes to the network, logs a warning, and can resolve after the snapshot.
- **Make the picture the same on every run.** Pin the clock with `mockDate` and write mock dates relative to it. Wait for content that renders only after the data arrives. Give self-measuring content a fixed width.
- **Each committed story shows a state no other story shows.** Every story adds a light and a dark baseline that every later change to that surface must approve again. A story written only to look at a change, or for a PR screenshot, is scratch: keep it out of the commit.
- **A story gets a fresh kea context, a fresh router and the default mocks.** Nothing carries over from the story before it, except module-level state such as `useAvailableFeatures`, which every story must set again.

## Shape of a story file

```tsx
import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { MyComponent } from './MyComponent'

const meta: Meta<typeof MyComponent> = {
  title: 'Components/My component',
  component: MyComponent,
  decorators: [
    mswDecorator({
      get: { '/api/environments/:team_id/my_things/': { results: [{ id: 1, name: 'First thing' }] } },
    }),
  ],
  parameters: {
    layout: 'padded',
    mockDate: '2024-01-15',
    featureFlags: [FEATURE_FLAGS.MY_FLAG],
    testOptions: { waitForSelector: 'text=First thing' },
  },
}
export default meta

type Story = StoryObj<typeof MyComponent>

export const Default: Story = {}

export const Empty: Story = {
  decorators: [mswDecorator({ get: { '/api/environments/:team_id/my_things/': { results: [] } } })],
  parameters: { testOptions: { waitForSelector: 'text=No things yet' } },
}
```

Storybook merges a story's `parameters` into the meta's: plain objects merge key by key at every depth, and every other value, arrays included, replaces the meta's value.
So a story's `testOptions: { waitForSelector }` keeps the meta's other `testOptions` keys.
An array `featureFlags` replaces the meta's list, so repeat the meta's flags in it. A record `featureFlags` merges with a meta record.

## Related

- [Deterministic stories](../../../docs/published/handbook/engineering/conventions/frontend-coding.md#deterministic-stories) in the frontend coding conventions lists the patterns that caused real quarantines, with the fix for each.
- [writing-ui-components](../writing-ui-components/SKILL.md) says when a component needs a story.
- [verifying-changes](../verifying-changes/SKILL.md) says when a Storybook render is enough to confirm a change.
- `common/storybook/.storybook/README.md` covers the local test runner and viewport widths.
