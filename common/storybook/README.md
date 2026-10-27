# Storybook

Storybook is where a UI change gets looked at before the stack runs.
CI also takes a light and a dark snapshot of each story, and visual review compares them with the baselines.

The setup lives in `common/storybook/.storybook/`:

- `main.ts` has the story globs and the Vite config.
- `preview.tsx` has the global decorators and parameters.
- `test-runner.ts` is the snapshot runner and reads the `testOptions` story parameters.
- `decorators/` has one file per global decorator.

More docs:

| Read                                           | When you                                                                                            |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| [Writing stories](docs/writing-stories.md)     | write a story, or set its feature flags, date, URL, layout, theme or tags                           |
| [Mocking data](docs/mocking-data.md)           | mock API responses, plan features, or the current user, team or preflight                           |
| [Snapshots](docs/snapshots.md)                 | pick `testOptions`, debug a timeout, an empty render or a flake, or need to know how baselines work |
| [Deterministic stories][deterministic-stories] | write a story that loads data, measures itself or uses timers, or fix one that flakes               |

[deterministic-stories]: ../../docs/published/handbook/engineering/conventions/frontend-coding.md#deterministic-stories

## Run it locally

```bash
pnpm storybook
```

Storybook indexes every story in the repo by default, and the first page load compiles all of it.
To work on a few stories, set `STORYBOOK_STORIES` to the directories or story files you need.
It takes a comma-separated list of paths relative to the repo root. A directory includes every `*.stories.{js,jsx,ts,tsx}` file under it.

```bash
STORYBOOK_STORIES=frontend/src/toolbar pnpm storybook
STORYBOOK_STORIES=frontend/src/scenes/insights,products/logs/frontend pnpm storybook
STORYBOOK_STORIES=frontend/src/lib/lemon-ui/LemonButton/LemonButton.stories.tsx pnpm storybook
```

Use the variable instead of editing the `stories` list in `main.ts`.
That edit is easy to commit by mistake, and it changes the set for every other run in the checkout.
Storybook reads the variable when it starts, so restart it to change the set.

A narrow set also helps when the sidebar shows no stories at all.
One story file the indexer can't parse empties the whole index, and a set that leaves it out still renders.

Without the variable, Storybook indexes the default roots in `main.ts`: `frontend/src`, `products/**/frontend`, `products/**/mcp/apps`, `services/mcp/src/ui-apps` and `packages/quill/packages/charts/src`.
A story file outside those roots is never served. CI never sets the variable.
`.github/scripts/verify-storybook-new-stories.sh` keeps its own copy of the default roots, so change both when you add a root.

### What `pnpm storybook` does

`pnpm storybook` runs the `start` script of `common/storybook` through turbo:

1. `pnpm build:products` generates the product manifests the app imports.
2. `pnpm build:workers` builds the web workers into `common/storybook/.workers`, which Storybook serves under `/static`. Without them every `new Worker(...)` gets a 404, and the error fails any story whose play function is still running.
3. `storybook dev -p 6006` starts the server.

Turbo drops env vars that a task doesn't declare.
`common/storybook/turbo.json` declares `STORYBOOK_STORIES` for `start`, so add any new variable that `main.ts` reads there too.

### Open one story

`http://localhost:6006/index.json` lists every story ID.
An ID is the kebab-case title, two dashes, then the kebab-case export name: `title: 'Scenes-Other/Toolbar'` with `export const Heatmap` is `scenes-other-toolbar--heatmap`.

This URL shows one story without the Storybook UI, in the theme you pick:

```text
http://localhost:6006/iframe.html?viewMode=story&id=<story-id>&globals=theme:dark
```

## Run the snapshot runner locally

CI takes the snapshots, so you rarely need this.
It helps when a story fails only in the runner, for example on a timeout.

The runner needs a static build, the same as in CI.
Against `pnpm storybook`, almost every story fails with `globalThis.__getContext is not a function`.
The build uses the same port, so stop the dev server first. Then, from `common/storybook`:

```bash
pnpm exec playwright install chromium
pnpm build:products && pnpm build:workers   # once, if `pnpm storybook` hasn't run them yet
STORYBOOK_STORIES=frontend/src/toolbar pnpm exec storybook build --test -o /tmp/storybook-static
pnpm exec http-server /tmp/storybook-static --port 6006 --silent &
STORYBOOK_STORIES=frontend/src/toolbar pnpm exec test-storybook --browsers chromium -u
```

- `test-storybook` reads the story list from `main.ts` in its own process, so give it the same `STORYBOOK_STORIES` as the build. Otherwise it collects every story in the repo, and each one the build doesn't have fails with "Couldn't find story matching id".
- `-u` writes fresh images. Without it, the runner compares each story with the image an earlier local run left in `frontend/__snapshots__/`, and an old image fails the story with a size or pixel diff.
- Images go to `frontend/__snapshots__/`. Git ignores the folder but still tracks some older PNGs in it, and `-u` rewrites them. Run `git status` afterwards and restore any tracked image the run changed.
- Failure images go to `frontend/__snapshots__/__failures__/` under the directory you ran from, so delete `common/storybook/frontend/` afterwards.
- These images are not the baseline. Visual review keeps the baseline hashes in `frontend/snapshots.yml`. See [Snapshots](docs/snapshots.md#baselines-and-visual-review).

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

The runner is `@storybook/test-runner`. See its [docs](https://storybook.js.org/docs/writing-tests/test-runner).

## Adding new Tailwind classes

`@tailwindcss/postcss` compiles Tailwind on the initial build.
Webpack's HMR does not re-run PostCSS when story content changes, so a newly used Tailwind utility (for example `bg-[rebeccapurple]`) won't appear until you restart Storybook.
Classes already present in the codebase hot-reload fine.

## Detect Storybook from app code

`lib/utils/dom.ts` has two checks:

- `inStorybook()` is true in any Storybook page.
- `inStorybookTestRunner()` is true only while the runner takes snapshots. The runner sets its user agent before any page script runs, so a check at module scope sees it too.

App code uses them to freeze values that change on every run, for example a fixed query ID in `dataNodeLogic` and a still progress bar in `LoadingBar`.
Prefer a mock or a parameter in the story. Use these checks only when the value comes from inside the component and no mock reaches it.
