# Running Storybook for a few stories

Storybook indexes every story in the repo by default.
To render a few stories, set `STORYBOOK_STORIES` instead of editing the `stories` list in `common/storybook/.storybook/main.ts`.
An edit there is easy to commit by mistake, and it changes the set for every other run in the checkout.

## Pick the stories

`STORYBOOK_STORIES` takes directories or story files, comma-separated and relative to the repo root.
A directory includes every `*.stories.{js,jsx,ts,tsx}` under it.

```sh
STORYBOOK_STORIES=frontend/src/toolbar pnpm storybook
STORYBOOK_STORIES=frontend/src/scenes/insights,products/logs/frontend pnpm storybook
STORYBOOK_STORIES=frontend/src/lib/lemon-ui/LemonButton/LemonButton.stories.tsx pnpm storybook
```

Without it, Storybook uses the full list in `main.ts`. CI never sets it.
Storybook reads the list when it starts, so restart it to change the set.

Narrow the set also when the index comes back empty or the sidebar shows no stories.
One story file that the indexer can't parse can do that to the whole index, so a narrow set that leaves it out still renders.

## Wait for it, then open a story

`pnpm storybook` builds products and workers before Storybook starts. It listens on port 6006 when ready.
The index lists the story IDs:

```sh
until curl -sf http://localhost:6006/index.json >/dev/null; do sleep 1; done
curl -s http://localhost:6006/index.json | jq -r '.entries | keys[]'
```

Open a story on its own, without the Storybook UI, and pick the theme in the URL:

```text
http://localhost:6006/iframe.html?viewMode=story&id=<story-id>&globals=theme:dark
```

The first page load after a start compiles the dependencies, and can take a few minutes.
Give a headless browser a page load timeout of a few minutes on that first load.

## Look at the result

Take screenshots with a Playwright script kept outside the repo, for example in `/tmp`.
Check the light and dark themes, and the narrow widths the root `AGENTS.md` asks for.
A story written only to look at a change is scratch. Keep it out of the commit.
