---
paths:
  - 'frontend/src/**/*.stories.tsx'
  - 'products/*/frontend/**/*.stories.tsx'
  - 'products/*/mcp/**/*.stories.tsx'
---

Every story here is a visual review snapshot.
A story that renders two different pictures for the same code blocks unrelated PRs in the merge queue.

Before you add or change a story, you MUST invoke the `/working-with-storybook` skill and read [Deterministic stories](../../docs/published/handbook/engineering/conventions/frontend-coding.md#deterministic-stories).
Every pattern listed there caused a real quarantine.

The causes that recur most:

- Time on screen without `parameters.mockDate`: relative dates, durations, elapsed query time.
- Async content the runner does not know about. Set `testOptions.waitForSelector` to an element that exists only after the data arrived, not to its container.
- A route change pushed by the story itself. Set the final URL with the `pageUrl` parameter instead.
- An unmocked request, which can resolve after the snapshot. Mock every request the story fires.
