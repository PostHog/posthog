# Running Storybook

## Start it for a few stories

Storybook indexes every story in the repo by default.
To render a few stories, set `STORYBOOK_STORIES` instead of editing the `stories` list in `common/storybook/.storybook/main.ts`.
An edit there is easy to commit by mistake, and it changes the set for every other run in the checkout.

`STORYBOOK_STORIES` takes directories or story files, comma-separated and relative to the repo root.
A directory includes every `*.stories.{js,jsx,ts,tsx}` under it.

```sh
STORYBOOK_STORIES=frontend/src/toolbar pnpm storybook
STORYBOOK_STORIES=frontend/src/scenes/insights,products/logs/frontend pnpm storybook
STORYBOOK_STORIES=frontend/src/lib/lemon-ui/LemonButton/LemonButton.stories.tsx pnpm storybook
```

Without it, Storybook indexes the default roots in `main.ts`: `frontend/src`, `products/**/frontend`, `products/**/mcp/apps`, `services/mcp/src/ui-apps` and `packages/quill/packages/charts/src`.
A story file outside those roots is never served. CI never sets the variable.
`.github/scripts/verify-storybook-new-stories.sh` keeps its own copy of the default roots, so change both when you add a root.

Storybook reads the list when it starts, so restart it to change the set.

Narrow the set also when the index comes back empty or the sidebar shows no stories.
One story file that the indexer can't parse can do that to the whole index, so a narrow set that leaves it out still renders.

## What `pnpm storybook` does

`pnpm storybook` runs the `start` script of `common/storybook` through turbo. hogli has no Storybook command.

1. `pnpm build:products` generates the product manifests the app imports.
2. `pnpm build:workers` builds the web workers into `common/storybook/.workers`. Storybook serves them under `/static`. Without them every `new Worker(...)` gets a 404, and the error fails any story whose play function is still running.
3. `storybook dev -p 6006` starts the server.

Turbo drops env vars that a task doesn't declare. `common/storybook/turbo.json` declares `STORYBOOK_STORIES` for `start`, so add a new variable there if `main.ts` starts to read one.

## Wait for it, then open a story

The server listens on port 6006 when ready. The index lists the story IDs:

```sh
until curl -sf http://localhost:6006/index.json >/dev/null; do sleep 1; done
curl -s http://localhost:6006/index.json | jq -r '.entries | keys[]'
```

A story ID is the kebab-case title, two dashes and the kebab-case export name. `title: 'Scenes-Other/Toolbar'` with `export const Heatmap` is `scenes-other-toolbar--heatmap`.

Open a story on its own, without the Storybook UI, and pick the theme in the URL:

```text
http://localhost:6006/iframe.html?viewMode=story&id=<story-id>&globals=theme:dark
```

The first page load after a start compiles the dependencies, and can take a few minutes.
Give a headless browser a page load timeout of a few minutes on that first load.

## Look at the result

Take screenshots with a Playwright script kept outside the repo, for example in `/tmp`.
Use `deviceScaleFactor: 2`, so a screenshot in a PR doesn't look soft.
Check the light and dark themes, and the narrow widths the root `AGENTS.md` asks for.
A story written only to look at a change is scratch. Keep it out of the commit.

## Run the snapshot runner locally

CI takes the snapshots, so you rarely need this. It helps when a story fails only in the runner, for example on a timeout.

The runner needs a static build, like CI. Against `pnpm storybook`, almost every story fails with `globalThis.__getContext is not a function`.
Stop the dev server first, because the build is served on the same port. From `common/storybook`:

```sh
pnpm exec playwright install chromium
pnpm build:products && pnpm build:workers   # once, if `pnpm storybook` hasn't run them yet
STORYBOOK_STORIES=frontend/src/toolbar pnpm exec storybook build --test -o /tmp/storybook-static
pnpm exec http-server /tmp/storybook-static --port 6006 --silent &
STORYBOOK_STORIES=frontend/src/toolbar pnpm exec test-storybook --browsers chromium -u
```

- `test-storybook` reads the story list from `main.ts` in its own process, so give it the same `STORYBOOK_STORIES` as the build. Without it, the runner collects every story in the repo, and each story the build doesn't have fails with "Couldn't find story matching id".
- `-u` writes fresh images. Without it, the runner compares each story with the image an earlier local run left in `frontend/__snapshots__/`, and an old image fails the story with a size or pixel diff.
- Images go to `frontend/__snapshots__/`, which git ignores. Failure images go to `frontend/__snapshots__/__failures__/` under the directory you ran from, so delete `common/storybook/frontend/` afterwards.
- These images are not the baseline. Visual review keeps the baseline hashes in `frontend/snapshots.yml`, see [snapshots-and-visual-review.md](snapshots-and-visual-review.md).

Other scripts in `common/storybook/package.json`:

| Script                  | What it does                                                                                          |
| ----------------------- | ----------------------------------------------------------------------------------------------------- |
| `test:visual:debug`     | Runs the runner with `PWDEBUG=1`, which opens the Playwright inspector, in Chromium and WebKit.       |
| `test:visual:update`    | Runs the runner in the Playwright Docker image against `host.docker.internal:6006` and writes images. |
| `test:visual:ci:update` | What CI runs: `test-storybook -u --junit --no-index-json --maxWorkers=2`.                             |

The runner reads these env vars:

| Variable                                                                  | Effect                                                                                                                |
| ------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `TARGET_URL`                                                              | The Storybook URL to test. The default is port 6006 on this machine.                                                  |
| `CI`                                                                      | Turns on the wait for network idle before each snapshot.                                                              |
| `STORYBOOK_INCLUDE_TAGS`, `STORYBOOK_EXCLUDE_TAGS`, `STORYBOOK_SKIP_TAGS` | Override which tags the runner collects, drops or skips. CI sets `STORYBOOK_SKIP_TAGS=test-skip,test-skip-<browser>`. |

## Detect Storybook from app code

`lib/utils/dom.ts` has two checks:

- `inStorybook()` is true in any Storybook page.
- `inStorybookTestRunner()` is true only while the runner takes snapshots. The runner sets its user agent before any page script runs, so a check at module scope also sees it.

App code uses them to freeze values that change on every run, for example a fixed query ID in `dataNodeLogic` and a still progress bar in `LoadingBar`.
Prefer a mock or a parameter in the story. Reach for these checks only when the value comes from inside the component and no mock reaches it.
