# hog

`hog` is the PostHog command line.
It replaces `posthog-cli` (in `cli/`), which keeps working until `hog` covers everything it does.

`hog` is written in TypeScript and compiles to a single binary with [Bun](https://bun.sh).
It is in alpha: the first release is 0.1.0-alpha.1.

## Install

```bash
curl -fsSL https://releases.posthog.com/hog/install.sh | sh        # macOS and Linux
irm https://releases.posthog.com/hog/install.ps1 | iex              # Windows PowerShell
brew install posthog/tap/hog                                        # Homebrew
npm install -g @posthog/hog                                         # or pnpm add -g, bun add -g
npx @posthog/hog setup                                              # run once without installing
```

- The install script picks the build for your OS, processor and C library (glibc or musl), checks it against `SHA256SUMS`, and puts `hog` in `~/.local/bin`. It tells you when that folder isn't on your `PATH`.
- `--version <version>` (or `HOG_VERSION`) installs another version, and `--dir <folder>` (or `HOG_INSTALL_DIR`) installs somewhere else: `curl -fsSL https://releases.posthog.com/hog/install.sh | sh -s -- --version 0.1.0-alpha.3`.
- Builds exist for macOS (Apple silicon and Intel), Linux (x64 and arm64, glibc and musl) and Windows (x64 and arm64).
- The npm package `@posthog/hog` is a small launcher. npm, pnpm and bun install only the `@posthog/hog-<platform>` package with the binary for your machine.

## Commands

`hog` has no `exp` namespace.
The commands `posthog-cli` keeps under `exp` (`query`, `endpoints`, `logs`, `tasks`, `schema`) are top-level commands in `hog`.

| Command                                   | Status                                                                                                                            |
| ----------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `hog setup`, `hog setup next`             | Takes this folder from nothing to PostHog installed and events arriving, one step at a time. See [Setup](#setup).                 |
| `hog auth login`                          | Logs in through the browser to one project, and names it in `posthog.json`. Agents finish with `hog auth login --wait`.           |
| `hog auth add <scope...>`                 | Adds scopes to your login, approved in the browser. Agents finish with `hog auth add --wait`.                                     |
| `hog auth status`                         | Shows whether hog is logged in, whose key it is, which login it picked and why. Exits with code 1 without a working key.          |
| `hog auth logout`                         | Removes the login commands in this folder use. `--all` removes every login.                                                       |
| `hog auth migrate`                        | Moves the key `posthog-cli login` saved into hog's store, so you don't have to log in again.                                      |
| `hog ci setup`                            | Asks an admin to trust this repository's CI jobs, so they use their OIDC token instead of a stored key.                           |
| `hog query run <query>`                   | Runs a HogQL query. `-` reads the query from stdin.                                                                               |
| `hog query check <query>`                 | Checks a query without running it. Exits with code 1 when the query has errors.                                                   |
| `hog api groups`, `hog api tools [group]` | List the PostHog MCP tools by group, with the scopes the key is missing for each.                                                 |
| `hog api search`, `info`, `schema`        | Find a tool, see what it does and the input it takes.                                                                             |
| `hog api call <tool> [input]`             | Calls a tool with JSON input. `--dry-run` only checks the input, and destructive tools need `--confirm`.                          |
| `hog api access`                          | Shows the key's scopes and the missing scopes that block the most tools.                                                          |
| `hog skills list`, `read`, `add`          | List every PostHog agent skill, read one, or add skills to this repository in the folder your agent reads. See [Skills](#skills). |
| `hog mcp add`                             | Connects PostHog's MCP server to your agent, with OAuth and no key in the file. See [MCP server](#mcp-server).                    |
| `hog error-tracking inject [paths...]`    | Adds chunk IDs to JavaScript bundles and their sourcemaps. `hog et` is an alias for `hog error-tracking`.                         |
| `hog error-tracking clone <from> <to>`    | Copies the chunk ID from Metro's map to the map Hermes composed, for React Native.                                                |
| `hog error-tracking upload [paths...]`    | Uploads symbols for readable stack traces: JavaScript sourcemaps, Hermes maps, ProGuard mappings, dSYMs and ELF files.            |
| `hog error-tracking process [paths...]`   | Runs `inject`, then `upload`. Use it in CI after the build.                                                                       |
| `hog error-tracking release`              | Finds or creates the release for this build. `-o text` prints just its ID.                                                        |
| `hog error-tracking download <id/ref>`    | Downloads a symbol set from PostHog and unpacks it.                                                                               |
| `hog error-tracking extract <file>`       | Unpacks a symbol set file.                                                                                                        |
| `hog endpoints list`, `get`, `open`       | List your endpoints a page at a time, show one, or open it in PostHog.                                                            |
| `hog endpoints run [name]`                | Runs an endpoint, or the query in a local file with `--file`. `--var name=value` sets variables.                                  |
| `hog endpoints pull`, `diff`, `push`      | Keep endpoints as YAML files: pull them, see how they differ, and push changes. `diff` exits with code 1 on drift.                |
| `hog schema pull`                         | Generates a typed SDK (TypeScript, Go or Python) from your event definitions, and records it in `posthog.json`.                   |
| `hog schema status`                       | Checks each generated SDK against PostHog. Exits with code 1 when one is missing or out of date.                                  |
| `hog config check`, `hog config schema`   | Check `posthog.json` against its schema, or print the schema.                                                                     |
| `hog commands`                            | Lists every command, its arguments, options and scopes.                                                                           |
| Everything else                           | Not ported yet. Exits with code 1 and prints the `posthog-cli` command to run instead, with the same arguments.                   |

## What's left

hog replaces posthog-cli in three steps: settle the CLI, ship it, then move everyone over.
[MIGRATING.md](MIGRATING.md) drafts the guidance for people moving from `posthog-cli` to `hog`, and it moves to posthog.com when hog ships.

First, settle the CLI:

- [ ] `hog upgrade`, which updates hog to the latest version. It downloads the release binaries, so it lands with distribution. Until then it points to `posthog-cli update`.
- The AGENTS.md snippet comes back as a top-level command, designed fresh rather than ported from `posthog-cli api agents-md`. Until then, hog points to it. `hog skills add` already replaces `posthog-cli api skill`.

Then ship it:

- [x] Distribution: a binary for each platform, macOS signing and notarization, the npm package and the Homebrew formula. See [Releases](#releases).
- [ ] CI on Linux and Windows: run the tests on Windows, and the install scripts on each platform.

Then move everyone over:

- [ ] Publish the migration guide on posthog.com.
- [ ] Callers: move the SDK build integrations (posthog-js, React Native and Expo, the Android Gradle plugin, the iOS build script), the error tracking onboarding in the web app, and the posthog.com docs from `posthog-cli` to `hog`.
- [ ] A `posthog-cli` entry point in hog that translates posthog-cli's commands, flags and `POSTHOG_CLI_` variables, so the posthog-cli package can ship hog and old pipelines and SDK versions keep working.

Not planned:

- `posthog-cli exp query editor`, the interactive query editor in the terminal. hog won't port it.
- `posthog-cli exp task`. hog won't port it.
- `posthog-cli exp logs import`, which imports historical logs from Loki. Not planned for now.

## Agents, people and pipes

`hog` detects an agent from the env vars agents set for the commands they run, such as `CLAUDECODE`, `CODEX_SANDBOX`, `CURSOR_AGENT`, `GEMINI_CLI` and the generic `AI_AGENT`.
`HOG_AGENT=1` forces agent mode, and `HOG_AGENT=0` turns detection off.

| Caller                 | Default output                            | Errors                                                           |
| ---------------------- | ----------------------------------------- | ---------------------------------------------------------------- |
| A person at a terminal | Text, with color unless `NO_COLOR` is set | Text on stderr                                                   |
| An agent               | JSON                                      | One JSON object on stderr: `{"error":{"code","message","hint"}}` |
| A pipe or a script     | JSON                                      | Same as an agent                                                 |

`-o text` or `-o json` overrides the default, and `--raw` prints a command's full result as JSON.
Exit codes: 0 on success, 1 when a command fails, 2 for a usage error.

## Setup

`hog setup` shows where the setup of this folder is, and changes nothing.
`hog setup next` does the current step, keeps going through every step that needs nobody, and stops at the first one that needs the person or the agent.
The setup is built for a coding agent: it asks the person one question, and runs `hog setup next` itself after each step.
A person at a terminal gets prompts for any answer the options leave out.
Agents get JSON: `{ step, status, code, done, next: { kind, command, ask, read, instructions }, context }`, where `next.kind` is `run`, `ask_user`, `tell_user`, `read`, `wait` or `done`.
[src/setup/README.md](src/setup/README.md) draws the steps for a person alone and for a person with an agent.

| Step        | `hog setup next`                                                                                                                                                              | Done when                                     |
| ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| `purpose`   | The agent asks "What do you want to use PostHog for?", and passes the answer as `--reason` and the matching product ids as `--products a,b`. `--region eu` is for EU hosting. | The answers are stored                        |
| `login`     | Starts a browser login to the chosen host, where new users can sign up, and returns. The next `hog setup next` waits for the approval.                                        | A login for this folder's host and project    |
| `project`   | Names the project in `posthog.json` and tells PostHog which products were picked. A failure there only warns.                                                                 | Always, once it ran                           |
| `agents-md` | Adds a note to `AGENTS.md`, and to `CLAUDE.md` when it doesn't import `AGENTS.md`, so a later session continues the setup.                                                    | Always, once it ran                           |
| `install`   | Returns the project token and host, and the two `hog skills read` commands that read the install skill and its rules.                                                         | Both files were read, and `next` ran after it |
| `review`    | Asks the agent to check its changes against the rules.                                                                                                                        | `--reviewed`, or yes at the terminal          |
| `verify`    | Looks for events PostHog received since the setup started. Exits with code 1 while there are none.                                                                            | An event arrived                              |
| `products`  | Lists the other products and the command that starts each, and the PostHog skills that could help later, which `hog skills add <skill...>` adds.                              | `--products-ack`, or shown at the terminal    |
| `mcp`       | Checks whether the agent running setup has PostHog's MCP server, and puts `{ agent, configured, command }` in `context.mcp`. Changes nothing.                                 | Never stops                                   |
| `connected` | Rewrites the note in `AGENTS.md` with the commands for later PostHog work. From then on `hog setup` shows a summary.                                                          | Always                                        |

The setup belongs to the folder of the closest `posthog.json`, or to the working folder when there is none, so each app in a monorepo has its own.
The answers, the start time, the skill files `hog skills read` served in that folder and the finished steps live in `~/.posthog/setup/`, one file per folder. Everything else is checked on each run.
Without that file, as in a fresh clone, the setup starts at the first step it can't prove done, and a clone whose `AGENTS.md` has the final note counts as set up.
The note sits between `<!-- posthog:setup:start -->` and `<!-- posthog:setup:end -->`, and nothing outside the markers changes.

## Skills

PostHog's agent skills are the step-by-step guides agents follow for PostHog tasks. `hog skills` alone shows the commands, and none of them needs a login.

```bash
hog skills list                                   # every skill
hog skills search session replay                  # find skills by keywords
hog skills read instrument-integration            # read a skill and list its files
hog skills read instrument-integration --file references/COMMANDMENTS.md
hog skills read instrument-integration --file references/django.md --lines 1:40
hog skills add instrument-integration             # copy it into this repository
```

Each `hog skills read` reads one skill, or one file in it with `--file`. A file too large to show whole comes back as an outline of its headings with line numbers, to read in parts with `--lines`. A skill name works with or without its `posthog:` prefix, and commands in the skill text name the hog commands.
hog downloads the latest PostHog product skills and the latest context-mill release, the same assets the MCP server serves, every time it runs.
It saves them in `~/.posthog/skills/` (`HOG_HOME` moves the folder), and serves that copy only when a download fails, saying when the copy was saved. Project skills are only available through the MCP server.

`hog skills add <skill...>` copies skills into the repository, so later agent sessions find them without hog.

- The list splits the skills into two kinds: skills for using PostHog, such as analyzing a funnel, from the PostHog product skills, and skills for adding PostHog to code, such as an SDK for one framework, from context-mill.
- Agents get the names only, grouped by kind, as `{ learning: [...], implementation: [...] }`. `hog skills search` returns descriptions.
- The output starts with the result, then the folders written, then any notes.
- They go in the closest git repository, or in the working folder outside of one. The output names which.
- Claude Code reads `.claude/skills/<id>/` and Augment reads `.augment/skills/<id>/`. Every other agent reads `.agents/skills/<id>/`, as in the agent table of [`npx skills add`](https://skills.sh).
- The folder follows the agent running the command. `--agent <name>` overrides it and can repeat. With no agent, the skills go in `.agents/skills/`.
- A skill that is already installed stays as it is, unless you pass `--force`.
- Agents get `{ root, rootKind, agentSource, skills: [{ name, agent, path, status }], assets }`, where `status` is `installed` or `already_installed`.

## MCP server

`hog mcp add` adds PostHog's MCP server to your agent's settings, in the same file and format as the Wizard, so either tool sees what the other added.

| Agent          | `--agent`        | File                                                                                                             |
| -------------- | ---------------- | ---------------------------------------------------------------------------------------------------------------- |
| Claude Code    | `claude-code`    | `.mcp.json` in the closest git repository, or in the working folder outside one                                  |
| Cursor         | `cursor`         | `~/.cursor/mcp.json`                                                                                             |
| Codex          | `codex`          | `~/.codex/config.toml`                                                                                           |
| VS Code        | `vscode`         | `mcp.json` in VS Code's user folder                                                                              |
| Zed            | `zed`            | `~/.config/zed/settings.json`, or under `XDG_CONFIG_HOME` on Linux                                               |
| opencode       | `opencode`       | `opencode.jsonc` or `opencode.json` in `OPENCODE_CONFIG_DIR`, `XDG_CONFIG_HOME/opencode` or `~/.config/opencode` |
| Claude Desktop | `claude-desktop` | `claude_desktop_config.json` in Claude's app data folder, on macOS and Windows                                   |

- The entry is the server URL, `https://mcp.posthog.com/mcp`, and never a key. The agent logs in to PostHog with OAuth the first time it connects.
- The server serves PostHog Cloud, so a self-hosted host stops the command.
- The agent running hog gets the server. `--agent <name>` overrides it and can repeat.
- Other servers and comments in the file are kept. An agent that already has a `posthog` entry for PostHog's MCP server keeps it, unless you pass `--force`. For Claude Code, such an entry `claude mcp add` put in `~/.claude.json` counts too.
- A `posthog` entry that connects to another server stops the command with `mcp_foreign_server`, and hog writes nothing. `--force` replaces it.
- Agents get `{ added: [{ agent, path, status }] }`, where `status` is `added`, `replaced` or `already_added`.

## Global options

Every option below works on any command, and each has an environment variable.
A flag beats the environment variable, which beats `posthog.json`.

| Option                    | Environment                        | `posthog.json`  | What it does                                                                                                                  |
| ------------------------- | ---------------------------------- | --------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `--host <url>`            | `HOG_HOST`                         | `host`          | The PostHog host to use instead of the one in your credentials                                                                |
|                           | `HOG_PROJECT_ID`                   | `projectId`     | The project to work in. It picks the stored login, and the project a personal API key or a CI job's token works in            |
| `--dotenv-file <path>`    | `HOG_DOTENV_FILE`                  |                 | Read credentials from this file when the environment has none                                                                 |
| `-o, --output <format>`   | `HOG_OUTPUT`                       |                 | `text` or `json`                                                                                                              |
| `--raw`                   | `HOG_RAW`                          |                 | Print a command's full result as JSON                                                                                         |
| `--debug`                 | `HOG_DEBUG`                        |                 | Print each HTTP request, its status and duration to stderr                                                                    |
| `--no-fail`               | `HOG_NO_FAIL`                      | `cli.noFail`    | Exit with code 0 when a command fails or reports a problem, such as `diff` finding drift. Usage errors still exit with code 2 |
| `--skip-ssl-verification` | `HOG_SKIP_SSL_VERIFICATION`        |                 | Accept any TLS certificate, for a self-signed self-hosted PostHog                                                             |
| `--no-telemetry`          | `HOG_NO_TELEMETRY`, `DO_NOT_TRACK` | `cli.telemetry` | Send no anonymous usage data. See [Telemetry](#telemetry)                                                                     |
| `--rate-limit <requests>` | `HOG_RATE_LIMIT`                   | `cli.rateLimit` | The most requests per minute. No limit by default                                                                             |
|                           | `HOG_DRY_RUN`                      |                 | Turns on `--dry-run` for every command that has one, and fails the commands that write without one                            |

`--host` and `HOG_HOST` override the host of every credential source. `host` in `posthog.json` never sends your credentials elsewhere: `hog auth login` uses it, and other commands stop when your credentials are for another host.
Commands that only read run as usual in a dry run, and `auth login` and `auth logout` fail.
hog reads only the `HOG_` names. posthog-cli's `POSTHOG_CLI_` variables, `POSTHOG_HOME` and `POSTHOG_RELEASE_MODE` don't count.

## Telemetry

hog sends usage events to PostHog, so the team can see who uses which commands and where they fail.

- `posthog cli command run`, once per command, the same event posthog-cli sends: the command, exit code, duration, the names of the options passed, the detected agent, the CI provider and runner (such as GitHub Actions on Depot or Blacksmith), the OS, and counts from the result, such as rows returned or endpoints pushed.
- `$exception` when a command fails, with the error code, message, hint and HTTP status. A message can name a file, or quote part of a query or an API answer.
- `error_tracking_cli_sourcemaps_upload_started`, `_finished` and `_endpoint_fallback`, as in posthog-cli.
- `hog setup started`, with your answer to what you want to use PostHog for, the products picked and the region, `hog setup step completed` with the step, and `hog setup completed`. The question says that hog sends the answer. With telemetry off, hog keeps it on your machine only.

With a PostHog Cloud key, events belong to your PostHog user, organization and project, the same ones the web app uses.
hog looks them up once per key with `/api/users/@me/` and `/api/projects/<id>/`, and keeps the answer in `~/.posthog/hog-telemetry-identity.json` for 30 days.
A CI job that uses its OIDC token counts as its workload instead: events carry an ID hashed from the provider and the repository, the provider's name and your organization, and no person.
Without a key, with a self-hosted PostHog, or with a key that can't read those, events belong to a random ID in `~/.posthog/hog-telemetry-id`.
Usage events never carry argument or option values or API keys, except the setup answer above.
When you log in, hog ties the random ID's earlier events to your PostHog user, so what you did before logging in, such as the first `hog setup` answers, counts with your sign-up.
`hog skills read` adds the names of the PostHog skills it served, how it read them, and whether each release came from the network or the saved copy. A name counts only once it matched a published skill, so the event never carries what you typed, such as a skill that doesn't exist. `hog skills search` adds only how many skills it found, never the keywords.

Telemetry is on by default and goes to the same PostHog project as posthog-cli's.
Turn it off with `--no-telemetry`, `HOG_NO_TELEMETRY=1`, `DO_NOT_TRACK=1`, or `"cli": { "telemetry": false }` in `posthog.json`.

## posthog.json

Project settings live in `posthog.json`, which hog looks for from the current folder up to the git root. The closest one wins.
It never holds API keys, so it can hold the `host` and `projectId` hog uses in CI.
`host` and `projectId` also pick which of your stored logins a command uses, so each app in a monorepo can work in its own project:

```text
repo/
├── apps/web/posthog.json   { "host": "https://us.posthog.com", "projectId": 1 }
└── apps/api/posthog.json   { "host": "https://us.posthog.com", "projectId": 2 }
```

Run `hog auth login` in `apps/web` and pick project 1, then in `apps/api` and pick project 2. Commands in each folder then use that folder's login. See [Logins and projects](#logins-and-projects).
When the file isn't valid, every command stops with `invalid_config` except `hog config check`, which lists the problems.
Point `$schema` at the published schema to get validation in your editor:

```json
{
  "$schema": "https://raw.githubusercontent.com/PostHog/posthog/master/hog/posthog.schema.json",
  "errorTracking": {
    "release": { "name": "my-app" },
    "sources": [{ "path": "app/build/outputs/mapping/release", "mapId": "<map id>" }]
  }
}
```

`errorTracking.releaseMode` sets the default for `--release-mode`. `HOG_RELEASE_MODE` overrides it.
`endpoints.dir` names the folder of endpoint files, so `hog endpoints pull`, `diff` and `push` work without a path.
`hog schema pull` keeps its entries under `languages` in the snake case posthog-cli uses, so either CLI can regenerate an SDK the other set up.
A `typescript` entry with `"sdk": "none"` holds event types only, with no posthog-js import, for posthog-react-native or any other SDK. `--sdk` sets it, and later pulls keep it.
posthog-cli rewrites `posthog.json` with only `languages` when it pulls, so it drops the other settings. Restore them from version control after running it.

`posthog.schema.json` is generated from `src/core/config.ts` with `pnpm --filter @posthog/hog schema`.

## Error tracking

`hog error-tracking` finds the artifacts in each path and detects their type from the files:

- a `.js`, `.mjs` or `.cjs` file is a JavaScript bundle when its sourcemap exists, through its `sourceMappingURL` comment or a `.map` file next to it
- a `.bundle` or `.jsbundle` file is a React Native bundle when its sourcemap exists
- a `.map` file is a Hermes map when it has `x_hermes_function_offsets`, which only the Hermes compiler writes
- a `.txt` file is a ProGuard or R8 mapping when its content parses as one
- a `.dSYM` folder is an Apple debug symbol bundle, and hog uploads each architecture in it separately
- any other file is an ELF or Mach-O binary when its first bytes say so. hog uploads it when it has debug info and a build ID or UUID, and lists why it skipped the others

Without paths, the commands read `errorTracking.sources` from `posthog.json`, where `ignore` globs skip files.
`--kind` skips detection.

JavaScript releases work in two modes, as in posthog-cli:

- `event`, the default, puts the release in the snippet hog adds to each bundle, so every event carries it. Chunk IDs come from the bundle content, so the same build gets the same IDs.
- `symbol-set` puts the release in the sourcemap, and gives a bundle a new random chunk ID when its release changes.

Release names and versions default to Git or supported CI metadata when omitted. Without that metadata, incomplete coordinates do not stop a build: `hog error-tracking release` returns `null`, and JavaScript and Hermes symbols can upload without a release. Symbol-set uploads warn when they cannot associate the symbols with a release. Pass both `--release-name` and `--release-version` to associate them in a Git-free build. Git read failures needed to complete the coordinates and release API failures still stop the command.

React Native with Hermes takes three steps, because the Hermes build runs between them:

```bash
hog error-tracking inject android/app/build/generated/assets         # before the Hermes build
hog error-tracking clone index.android.bundle.map index.android.bundle.hbc.composed.map
hog error-tracking upload android/app/build/generated/sourcemaps     # the composed maps
```

hog uploads the same bytes and content hashes as posthog-cli, so either CLI can re-upload what the other uploaded. A few things differ on purpose:

- `posthog-cli sourcemap`, `hermes`, `proguard`, `dsym` and `symbol-sets upload` are `hog error-tracking`, with paths as arguments instead of `--directory` and `--path`
- hog reads dSYM bundles itself, so it needs neither Xcode's `dwarfdump` nor `lipo`, and uploads dSYMs from Linux too
- `--include-source` reads a binary's DWARF itself, with the same rules as posthog-cli, to bundle the source files it names. Where posthog-cli crashes on a malformed binary, hog uploads it without sources
- native releases come from the flags, `posthog.json` or git, as in `posthog-cli symbol-sets upload`. hog doesn't read the release from the dSYM's `Info.plist`, as `posthog-cli dsym upload` does
- `upload` sends only Hermes maps it detects. posthog-cli treats every JSON file in the folder as a map, and fails when it finds Metro's map there
- hog walks folders in sorted order and skips `node_modules`, `.git` and symlinks, so two machines visit the same files in the same order
- `--dry-run` shows the plan and the content hashes without writing files or contacting PostHog. posthog-cli's `--dry-run` skips the whole command.

## Credentials

`hog` reads credentials from these sources, in order:

1. `HOG_PERSONAL_API_KEY` in the environment, with the project ID in `posthog.json` as `projectId` or in `HOG_PROJECT_ID`, plus an optional `HOG_HOST`. The key is a personal API key: it acts as you, with your access. Never put it in `posthog.json`.
2. The same variables in the file `--dotenv-file` or `HOG_DOTENV_FILE` names. A missing file prints a warning and hog moves on to the next source.
3. In a CI job of a supported provider, with the project ID in `posthog.json` or `HOG_PROJECT_ID`, the job's OIDC token. See [CI without a stored key](#ci-without-a-stored-key).
4. What `hog auth login` stored, one login per host and project: a short-lived OAuth token for that project, or a personal API key you pasted. It lives in the system keychain (Keychain on macOS, Credential Manager on Windows, Secret Service on Linux), or `credentials.json` in hog's folder when hog can't use the keychain, such as over SSH or in a container. Only you can read that file.

hog doesn't read `~/.posthog/credentials.json`, the file `posthog-cli login` writes (`HOG_HOME` moves the folder). Run `hog auth migrate` once to move its key into hog's store.

`--host` and `HOG_HOST` override the host from any of these.
A `host` in `posthog.json` never sends a key to a host it wasn't made for.

### Logins and projects

An OAuth token works in the one project you picked when you approved it, so hog keeps one login per host and project.
A command picks a login from the closest `posthog.json`:

| What names the host and project                       | Login hog uses                                                                               |
| ----------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| The closest `posthog.json` has `host` and `projectId` | The login for that host and project                                                          |
| `--host`, `HOG_HOST` or `HOG_PROJECT_ID` is set       | They replace the values in `posthog.json`, then hog uses the login for that host and project |
| Nothing names a project                               | Your latest login to the host that is named, or else to the host you last logged in to       |
| A project is named, and hog has no login for it       | None. The command stops with `project_mismatch`, and `hog auth login` adds the login         |

`posthog.json` with a `projectId` and no `host` means that project on the host you last logged in to. When `--host` or `HOG_HOST` names another host than `posthog.json`, its `projectId` doesn't count, because a project ID belongs to one host.
`hog auth status` names the `posthog.json` it found, the login it picked and why.
A personal API key in `HOG_PERSONAL_API_KEY` and a CI job's token don't use stored logins: they take the project from `HOG_PROJECT_ID` or `posthog.json`.

hog's folder is `~/Library/Application Support/hog` on macOS, `$XDG_CONFIG_HOME/hog` or `~/.config/hog` on Linux, and `%LOCALAPPDATA%\hog` on Windows.

### CI without a stored key

A CI job can trade the OIDC token its provider issues for a PostHog token, so no key is stored in the CI provider.
hog supports GitHub Actions, GitLab.com and Depot CI.
An organization admin trusts the repository once, and each run of the job then gets a token that lives a few minutes.

1. In the repository, logged in with `hog auth login`, run `hog ci setup --scope error_tracking:write`, listing every scope the job needs, separated by commas, like `--scope error_tracking:write,query:read`. hog asks which runs may get a token, such as pushes to a branch or deploys to an environment, with the presets and explanations PostHog offers for the provider. Pass them as options instead, like `--preset branch_push=main`. An agent gets the list of presets it still needs, with the same explanations.
2. hog finds the CI provider and the repository from the origin remote, and asks PostHog to trust it in your project. When the repository has config for more than one provider, such as `.github/workflows` next to `.depot/workflows`, pass `--provider depot_ci` or `--provider github_actions`. PostHog looks up the repository's ID, so a deleted and re-created repository with the same name doesn't match.
3. An organization admin approves the request in the browser. When you are one, hog opens the page and waits. Otherwise it names the admins and prints the link to send them. `hog ci setup --wait` checks on the request later.
4. Add the `host` and `projectId` hog prints to `posthog.json`, and the snippet it prints to the job, which gives the job an OIDC token. Setting `HOG_HOST` and `HOG_PROJECT_ID` in the job works too, and a self-hosted PostHog needs `HOG_HOST`.

In the job:

- hog asks the provider for a token whose audience is the PostHog host, and exchanges it for a token that works in the project with the scopes the admin allowed.
- Put the project ID and the host in `posthog.json` as `projectId` and `host`, which is simpler than setting `HOG_PROJECT_ID` and `HOG_HOST` in every job. The environment variables win when both are set.
- A `host` in `posthog.json` counts here only when it is PostHog Cloud (`https://us.posthog.com` or `https://eu.posthog.com`), so a change to the file can't send the job's token elsewhere. A self-hosted PostHog needs `HOG_HOST`, and a job stops when posthog.json names one without it. Without either, hog uses `https://us.posthog.com`.
- The token lives a few minutes. hog keeps it in memory for the run, never on disk, and exchanges again before it expires.
- `HOG_PERSONAL_API_KEY` still wins when it is set.

### Logging in and out

- At a terminal, `hog auth login` asks where your PostHog account is hosted, opens the browser, and waits for you to approve. The address PostHog opens at, us.posthog.com or eu.posthog.com, tells you which to pick.
- On the approval page you check the code, pick a project and see what hog will be able to do. The token only works in that project, and it renews automatically.
- Each project keeps its own login, and logging in to another project keeps the others. `hog auth login` writes the host and project to `posthog.json` in the current folder, or to the closest one above it, and says which file it changed.
- `hog auth login --read-only` asks only for read access. To change something later, run `hog auth add` with the write scopes you need.
- `hog auth add insight:write dashboard:write` adds scopes to your login. hog asks for the scopes you already have plus the new ones, and the approval page keeps the new ones ticked. In the same project, commands that are still running keep working with the new token. Agents finish with `hog auth add --wait`.
- When PostHog refuses a request because your login lacks a scope, hog asks at a terminal whether to add it with `hog auth add`, then sends the request again. Agents get the error `step_up_required` with the `hog auth add` command to run. A personal API key gets the scopes to add to the key in PostHog.
- `hog error-tracking upload`, `hog error-tracking process`, `hog endpoints push` and `hog api call` check your scopes before they change anything, so they don't stop halfway.
- An agent or a script cannot answer prompts, so `hog auth login --region us` returns at once with a link and a code for a person to approve. `hog auth login --wait` then saves the token. Running `hog auth login` again before the code expires returns the same link.
- Each login checks that hog can use the keychain, and records where it stored the token in `settings.json` in hog's folder, so other commands don't check again. The keychain, or the credentials file, keeps only the secrets. The rest of the login, such as the project and the scopes, is in `settings.json`. When the keychain shows a dialog, choose "Always Allow".
- Self-hosted PostHog has to reach posthog.com to log hog in, because hog's OAuth client is described there. Without that, set the environment variables above.
- In CI, skip login. Use the job's OIDC token (below), or set the environment variables above.
- `hog auth status` checks the credentials against PostHog, and names where they come from, their scopes and when the token expires. `hog auth logout` revokes the login commands in this folder use, the one `hog auth status` shows, and removes it from this machine. `hog auth logout --all` does the same for every login hog stored. Both warn when an environment variable still holds a key.

## Develop

Each command is one file under `src/commands/`, and declares what people and agents see separately.
[AGENTS.md](AGENTS.md) has the layout and the steps to add a command.

Install [Bun](https://bun.sh) 1.3.3 or later, then from the repo root:

```bash
pnpm --filter @posthog/hog hog --help       # run hog from source
pnpm --filter @posthog/hog unit             # run the tests
pnpm --filter @posthog/hog typecheck        # check types
pnpm --filter @posthog/hog compile          # build dist/hog for this machine
```

hog reads credentials only from the sources above. Runs from source keep their keychain items under their own name, so they never read or replace an installed hog's login. Bun would otherwise load a `.env` or `bunfig.toml` from the working folder, so the scripts turn that off. Older Bun versions ignore those flags, hence the minimum version.

## Releases

hog releases the way posthog-cli does: a sampo changeset says what changed, and a person approves each release.
The `Release hog` workflow (`.github/workflows/release-hog.yml`) runs it, and `release/` holds its scripts.

To release a change, add a changeset to your pull request from `hog/`:

```bash
sampo add --package npm/@posthog/hog --bump patch --message "Describe the change for the changelog"
```

Use `minor` or `major` instead of `patch` when it fits. While the version is a prerelease, such as `0.1.0-alpha.3`, every bump raises the prerelease number. Commit the file sampo writes under `hog/.sampo/changesets/`.

After the pull request merges to master, the workflow:

1. Posts an approval request in the hog releases Slack channel.
2. Waits for approval in the `hog-release` environment. The authors and mergers of the released pull requests can't approve, and a hog change merged after the run started stops it.
3. Runs `sampo release`, which bumps `hog/package.json` and writes `hog/CHANGELOG.md`, and opens a release pull request with the bump. A second App approves it, and it goes through the merge queue.

Merging the release pull request runs the workflow again, which:

4. Compiles every target, with the version and the release commit's date as the build date.
5. Signs and notarizes the macOS builds in the `hog-publish` environment, which has no reviewers, admits only master, and is the only environment the release bucket trusts. A missing certificate or notarization credential fails the release.
6. Uploads to `releases.posthog.com/hog/v<version>/`, then creates the GitHub release and the `hog/v<version>` tag, then points `hog/latest/manifest.json`, the install scripts and `Formula/hog.rb` in `PostHog/homebrew-tap` at it, and publishes the npm packages.

A release takes two merges, the changeset and then the release pull request, and one approval.

- Re-run the failed jobs to finish a release that stopped. Files under a version never change: once a version's upload is complete, a rerun reuses its files instead of signing again. An upload that stopped halfway starts over. GitHub, npm and the formula skip what they already have.
- Every release is the latest, prereleases included. A rerun of an older version never moves `hog/latest/manifest.json`, npm's `latest` tag or the formula back.
- To retire a broken release, set `minimumVersion` in `release/minimum-version.json`. The next release carries it in its manifest.
- Don't run `sampo publish` or push `hog/v*` tags by hand.

```bash
bun release/compile.ts --version 0.1.0-alpha.9 --target darwin-arm64   # a release build for this machine
bun test release/                                                       # the install script and launcher tests
```
