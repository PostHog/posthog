# hog

`hog` is the PostHog command line, version 1.
It replaces `posthog-cli` (version 0, in `cli/`), which keeps working until `hog` covers everything it does.

`hog` is written in TypeScript and compiles to a single binary with [Bun](https://bun.sh).
It is not published yet.

## Commands

`hog` has no `exp` namespace.
The commands `posthog-cli` keeps under `exp` (`query`, `endpoints`, `logs`, `tasks`, `schema`) are top-level commands in `hog`.

| Command                                 | Status                                                                                                                  |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `hog auth login`                        | Logs in through the browser and saves a personal API key. Agents finish with `hog auth login --wait`.                   |
| `hog auth status`                       | Shows whether hog is logged in, whose key it is, and where the key comes from. Exits with code 1 without a working key. |
| `hog auth logout`                       | Removes the stored key. The key stays valid in PostHog until you delete it there.                                       |
| `hog query run <query>`                 | Runs a HogQL query. `-` reads the query from stdin.                                                                     |
| `hog query check <query>`               | Checks a query without running it. Exits with code 1 when the query has errors.                                         |
| `hog error-tracking inject [paths...]`  | Adds chunk IDs to JavaScript bundles and their sourcemaps. `hog et` is an alias for `hog error-tracking`.               |
| `hog error-tracking upload [paths...]`  | Uploads symbols for readable stack traces: JavaScript sourcemaps, and ProGuard and R8 mappings.                         |
| `hog error-tracking process [paths...]` | Runs `inject`, then `upload`. Use it in CI after the build.                                                             |
| `hog config check`, `hog config schema` | Check `posthog.json` against its schema, or print the schema.                                                           |
| `hog commands`                          | Lists every command, its arguments, options and scopes.                                                                 |
| Everything else                         | Not ported yet. Exits with code 1 and prints the `posthog-cli` command to run instead, with the same arguments.         |

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

## posthog.json

Project settings live in `posthog.json`, which hog looks for from the current folder up to the git root.
It never holds API keys.
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

`posthog.schema.json` is generated from `src/core/config.ts` with `pnpm --filter @posthog/hog schema`.

## Error tracking

`hog error-tracking` finds the artifacts in each path and detects their type from the files:

- a `.js`, `.mjs` or `.cjs` file is a JavaScript bundle when its sourcemap exists, through its `sourceMappingURL` comment or a `.map` file next to it
- a `.txt` file is a ProGuard or R8 mapping when its content parses as one

Without paths, the commands read `errorTracking.sources` from `posthog.json`, where `ignore` globs skip files.
`--kind` skips detection.

JavaScript releases work in two modes, as in posthog-cli:

- `event`, the default, puts the release in the snippet hog adds to each bundle, so every event carries it. Chunk IDs come from the bundle content, so the same build gets the same IDs.
- `symbol-set` puts the release in the sourcemap, and gives a bundle a new random chunk ID when its release changes.

hog uploads the same bytes and content hashes as posthog-cli, so either CLI can re-upload what the other uploaded. A few things differ on purpose:

- `posthog-cli sourcemap` and `posthog-cli proguard` are `hog error-tracking`, with paths as arguments instead of `--directory` and `--path`
- hog walks folders in sorted order and skips `node_modules`, `.git` and symlinks, so two machines visit the same files in the same order
- `--dry-run` shows the plan and the content hashes without writing files or contacting PostHog. posthog-cli's `--dry-run` skips the whole command.

## Credentials

`hog` reads the same credentials as `posthog-cli`, in the same order:

1. `POSTHOG_CLI_API_KEY` and `POSTHOG_CLI_PROJECT_ID` in the environment, plus an optional `POSTHOG_CLI_HOST`
2. The same variables in the file `--dotenv-file` names
3. `~/.posthog/credentials.json`, which `hog auth login` and `posthog-cli login` write (`POSTHOG_HOME` moves the folder). `hog auth login` makes it readable only by you.

`--host` overrides the host from any of these.

### Logging in and out

- At a terminal, `hog auth login` asks where your PostHog account is hosted, opens the browser, and waits for you to approve. The address PostHog opens at, us.posthog.com or eu.posthog.com, tells you which to pick.
- An agent or a script cannot answer prompts, so `hog auth login --region us` returns at once with a link and a code for a person to approve. `hog auth login --wait` then saves the key. Running `hog auth login` again before the code expires returns the same link.
- In CI, skip login and set the environment variables above.
- `hog auth status` checks the key against PostHog. `hog auth logout` warns when an environment variable still holds a key.

## Develop

Each command is one file under `src/commands/`, and declares what people and agents see separately.
[AGENTS.md](AGENTS.md) has the layout and the steps to add a command.

Install [Bun](https://bun.sh), then from the repo root:

```bash
pnpm --filter @posthog/hog hog --help       # run hog from source
pnpm --filter @posthog/hog unit             # run the tests
pnpm --filter @posthog/hog typecheck        # check types
pnpm --filter @posthog/hog compile          # build dist/hog for this machine
```
