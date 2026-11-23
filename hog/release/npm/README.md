# hog

hog is the PostHog command line.
It adds PostHog to your app, runs queries against your data, calls the PostHog API, and uploads source maps and debug symbols from CI.

It works for a person at a terminal and for coding agents such as Claude Code, Codex and Cursor.
When an agent runs hog, or its output goes to a pipe, hog prints JSON.

## Install

```bash
npm install -g hog          # or pnpm add -g hog, or bun add -g hog
npx hog setup               # run it once without installing
```

To pin hog in a project, add it as a dev dependency with the package manager the project already uses, such as `npm install --save-dev hog`.

hog also installs with Homebrew or a script:

```bash
brew install posthog/tap/hog
curl -fsSL https://releases.posthog.com/hog/install.sh | sh      # macOS and Linux
irm https://releases.posthog.com/hog/install.ps1 | iex           # Windows PowerShell
```

`hog upgrade` updates hog however you installed it.

## Add PostHog to your app

Run this in your app's folder, or ask your coding agent to run it:

```bash
hog setup
hog setup next
```

`hog setup` shows where the setup stands. `hog setup next` does the next step.
The steps ask what you want to use PostHog for, log you in through the browser, give your agent the instructions to install the PostHog SDK, and check that events arrive.
An agent runs `hog setup next` after each step and asks you only what it can't decide.

## Log in

```bash
hog auth login      # log in through the browser
hog auth status     # see who hog is logged in as, and for which project
```

hog keeps the login in your system keychain, or in a file only you can read when there is no keychain, and names the project in `posthog.json`.

## Query your data

```bash
hog query run "select event, count() from events group by event order by count() desc limit 10"
cat query.sql | hog query run -
```

Queries are [HogQL](https://posthog.com/docs/hogql), PostHog's SQL.

## Call the PostHog API

hog reaches the PostHog API through the same tools the PostHog MCP server offers:

```bash
hog api search feature flag                               # find a tool
hog api info feature-flag-get-all                         # see what it does and the input it takes
hog api call feature-flag-get-all '{"limit": 5}'          # call it
hog api call delete-feature-flag '{"id": 12}' --confirm   # tools that delete something need --confirm
```

`--dry-run` checks the input without calling the tool. `hog api access` shows which scopes your login is missing.

## Upload source maps and debug symbols

Run this in CI after the build, so error tracking shows readable stack traces:

```bash
hog error-tracking process dist
```

It handles JavaScript source maps, Hermes maps, ProGuard mappings, dSYMs and ELF files.

In CI, hog can use the job's OIDC token instead of a stored key. Run `hog ci setup --scope error_tracking:write` once to ask a PostHog admin to trust the repository. Otherwise, set `HOG_PERSONAL_API_KEY` and `HOG_PROJECT_ID` in the CI environment.

## Give your agent PostHog

```bash
hog mcp add                     # connect PostHog's MCP server to your agent
hog skills list                 # list PostHog's agent skills
hog skills add <skill...>       # add skills to this repository, in the folder your agent reads
```

## More

- `hog --help` lists the commands, and `hog <command> --help` shows the options and examples for one.
- `hog commands -o json` describes every command for agents and scripts.
- `hog feedback "<message>"` sends feedback to the PostHog team.
- The [hog README](https://github.com/PostHog/posthog/tree/master/hog#readme) covers every command, the exit codes and the settings.
- Moving from `posthog-cli`? Follow the [migration guide](https://github.com/PostHog/posthog/blob/master/hog/MIGRATING.md).
