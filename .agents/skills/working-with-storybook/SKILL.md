---
name: working-with-storybook
description: >
  Runs, writes and debugs PostHog Storybook stories and their visual review snapshots.
  Use when you start Storybook to look at a change, write or change a `*.stories.tsx` file,
  set feature flags, the date, the URL, mocks or `testOptions` for a story,
  or fix a story that times out, renders nothing or flakes in visual review, including the offline baseline check on a fork PR.
  Points to the Storybook docs in `common/storybook/` and adds the steps an agent follows to render and screenshot a story.
  Trigger terms: storybook, story, stories, pnpm storybook, STORYBOOK_STORIES, featureFlags, testOptions,
  mswDecorator, mockDate, visual review, snapshot, flaky story, Visual regression tests pass.
---

# Working with Storybook

The Storybook docs live next to the setup, in [common/storybook/README.md](../../../common/storybook/README.md) and its `docs/` folder.
This skill does not repeat them. Read the one the task needs:

| Task                                                                                | Read                                                                                                                       |
| ----------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Start Storybook, open a story by URL, run the snapshot runner locally               | [README](../../../common/storybook/README.md)                                                                              |
| Write a story, or set its feature flags, date, URL, layout, theme or tags           | [Writing stories](../../../common/storybook/docs/writing-stories.md)                                                       |
| Mock API responses, plan features, the current user, team or preflight              | [Mocking data](../../../common/storybook/docs/mocking-data.md)                                                             |
| Pick `testOptions`, fix a timeout, an empty render or a flake, understand baselines | [Snapshots](../../../common/storybook/docs/snapshots.md)                                                                   |
| Write a story that loads data, measures itself or uses timers                       | [Deterministic stories](../../../docs/published/handbook/engineering/conventions/frontend-coding.md#deterministic-stories) |
| Find out why visual review blocks a PR, approve, tolerate or quarantine a snapshot  | [triaging-visual-review-runs](../../../products/visual_review/skills/triaging-visual-review-runs/SKILL.md)                 |

## Render a story to check a change

1. Start Storybook in the background with only the stories you need: `STORYBOOK_STORIES=<dir or story file> pnpm storybook`. Never edit the `stories` list in `common/storybook/.storybook/main.ts`.
2. Wait for the index, then find the story ID:

   ```sh
   until curl -sf http://localhost:6006/index.json >/dev/null; do sleep 1; done
   curl -s http://localhost:6006/index.json | jq -r '.entries | keys[]'
   ```

3. Load `http://localhost:6006/iframe.html?viewMode=story&id=<story-id>&globals=theme:<light|dark>` in a headless browser. The first load after a start compiles the dependencies and can take a few minutes, so give it a page load timeout of a few minutes.
4. Take screenshots with a Playwright script kept outside the repo, for example in your scratch directory. Use `deviceScaleFactor: 2`, so a screenshot in a PR doesn't look soft.
5. Check the light and dark themes, and the narrow widths the root `AGENTS.md` asks for. Compare before and after.

A story you write only for this check or for a PR screenshot is scratch. Keep it out of the commit.

## Before you commit a story

- Read [Writing stories](../../../common/storybook/docs/writing-stories.md) first when the story sets feature flags. The wrong way passes in jest and fails only in visual review.
- Each committed story shows a state no other story shows, because each one adds two baselines that every later change must approve again.
- Don't commit images from a local snapshot run. CI takes the snapshots, and visual review commits the baseline hashes.

## Visual review in this repo

`triaging-visual-review-runs` is published to every PostHog user, so it says nothing about this repo's CI. Use it together with these facts:

- Branch protection requires the `Visual regression tests pass` and `Playwright tests pass` job checks.
- A PR run renders only the stories its diff can affect. The `run-ci-frontend` label asks for every story, from the next push on. [Snapshots](../../../common/storybook/docs/snapshots.md#baselines-and-visual-review) has the details.
- A fork PR has no Visual Review run. Each Storybook shard compares its screenshots with `frontend/snapshots.yml` in the `Verify snapshots against the baseline offline` step, and a mismatch fails `Visual regression tests pass`. Triage it with the fork section of the triaging skill. [Pull requests from forks](../../../docs/published/handbook/engineering/fork-pull-requests.md) explains the fallback, and `recreating-fork-prs` moves a reviewed fork PR in-repo.
- To find the story file behind a snapshot, search for its title, for example `rg "title: 'Scenes-App/Settings/User'" frontend products`.
