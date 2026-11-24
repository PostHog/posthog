# Moving from posthog-cli to hog

> [!NOTE]
> This guide is duplicated at https://posthog.com/docs/cli/migrating.

hog is the successor to posthog-cli. It does what posthog-cli does, with new command names, `HOG_` environment variables, and output that agents can read.

This guide is written for a coding agent to follow from top to bottom, and a person can follow it the same way.
The steps move one repository: its scripts, its CI and the machine you work on.
The sections after the steps are the reference: every variable, command and flag that changed.

## The goal

- Nothing in the repository runs `posthog-cli`, depends on `@posthog/cli`, or reads a `POSTHOG_CLI_` variable.
- The build uploads the same symbols with hog. hog sends the same bytes and content hashes, so keep the release names, paths and settings as they are.
- In GitHub Actions, GitLab.com and Depot CI, the job logs in with its OIDC token instead of a stored personal API key.

Some steps need a person. When you reach one, stop, say what they need to do and why, and continue once they confirm.
[Steps for a person](#steps-for-a-person) lists them.

## 1. Find where posthog-cli runs

Search the whole repository, including hidden folders:

```bash
git grep -n -E 'posthog-cli|@posthog/cli|POSTHOG_CLI_|POSTHOG_CLIENT_RATE_LIMIT|POSTHOG_RELEASE_MODE|POSTHOG_HOME'
```

Look in particular at:

- `package.json`: `@posthog/cli` as a dependency, and scripts that call `posthog-cli`. Leave lockfiles to the package manager.
- CI config: `.github/workflows/`, `.gitlab-ci.yml`, `.depot/workflows/`, `.circleci/`, `bitbucket-pipelines.yml`, `Jenkinsfile`, `vercel.json`, `netlify.toml`.
- Build scripts: Dockerfiles, Makefiles, shell scripts, Fastlane lanes, Gradle tasks and Xcode build phases.
- Environment files: `.env*`, and any file passed with `--dotenv-file`.
- The names of CI secrets, such as `POSTHOG_CLI_API_KEY`. You can't read their values, and you don't need to.

Also look for a PostHog build plugin: `@posthog/nextjs-config`, `@posthog/webpack-plugin`, `@posthog/rollup-plugin` or `@posthog/nuxt`. A plugin runs the CLI for the build, so [it changes differently](#build-plugins).

List what you found before you change anything, so the person can check it.

## 2. Install hog

Use the package manager the project already uses. Its lockfile tells you which one:

| Lockfile                  | Add hog to the project | Install hog globally | Run hog once   |
| ------------------------- | ---------------------- | -------------------- | -------------- |
| `package-lock.json`       | `npm install -D hog`   | `npm install -g hog` | `npx hog`      |
| `pnpm-lock.yaml`          | `pnpm add -D hog`      | `pnpm add -g hog`    | `pnpm dlx hog` |
| `yarn.lock`               | `yarn add -D hog`      | `npm install -g hog` | `yarn dlx hog` |
| `bun.lock` or `bun.lockb` | `bun add -d hog`       | `bun add -g hog`     | `bunx hog`     |

Yarn 2 and later have no global installs, and Yarn 1 has no `dlx`, so use npm for those.

When the project ran posthog-cli through `@posthog/cli` in `package.json`, remove `@posthog/cli` and add `hog` with that package manager, so the lockfile changes with it.
When it installed posthog-cli globally in CI, install hog the same way, with the same package manager.

A project without Node, or a machine without a project, can use Homebrew or the install script:

```bash
brew install posthog/tap/hog
curl -fsSL https://releases.posthog.com/hog/install.sh | sh   # macOS and Linux
```

Every install puts `hog-worker`, the program hog runs for `hog error-tracking`, next to `hog`.
posthog-cli is one file and hog is two, so a Dockerfile or CI cache that copied the `posthog-cli` binary must copy both `hog` and `hog-worker` into the same folder.

`hog upgrade` replaces `posthog-cli update`.

## 3. Log in on the machine

- Run `hog auth migrate` when posthog-cli was logged in on this machine. It moves that login to hog.
- Otherwise run `hog auth login`. An agent gets a link and exit code 3: give the link to the person, and run `hog auth login --wait` once they approve.

`hog auth status` shows which login hog uses and why.

## 4. Log in from CI

### GitHub Actions, GitLab.com and Depot CI

Use the job's OIDC token, so CI stores no key at all.
Each run gets a PostHog token that lasts a few minutes, works in one project, and has only the scopes an admin allowed.

1. In the repository, logged in, run `hog ci setup --scope error_tracking:write`. List every scope the job needs, like `--scope error_tracking:write,query:read`.
2. hog asks which runs may get a token, such as pushes to `main`. An agent gets the presets PostHog offers: ask the person which one fits, and pass it with `--preset`.
3. An organization admin approves the request in PostHog. This needs a person. `hog ci setup --wait` checks on it.
4. Add the `host` and `projectId` that hog prints to `posthog.json`, and the snippet it prints to the job. The snippet lets the job get an OIDC token.
5. Remove `POSTHOG_CLI_API_KEY` from the job. `HOG_PERSONAL_API_KEY` wins over OIDC, so don't set it either.

Once a run passes, the person deletes the old key from the CI secrets, and deletes it in PostHog if nothing else uses it.

### Every other CI provider

Rename the variables the job sets, with [the table below](#environment-variables).
The secret keeps its value. Only the variable the job sets changes, so the job can set `HOG_PERSONAL_API_KEY` from the same secret until someone renames it.

## 5. Rewrite the commands

Replace each command with the [commands table](#commands), and check its flags against [flags that changed](#flags-that-changed).
A script that reads hog's output passes `-o text` or `-o json`, as [Output](#output) explains.

## Build plugins

When a PostHog build plugin is the only thing that runs posthog-cli, update the plugin to its latest version, which runs hog itself.
The plugin config stays the same.

In GitHub Actions, GitLab.com and Depot CI, the plugin can use the job's OIDC token too:
run `hog ci setup` as in [step 4](#4-log-in-from-ci), then remove `personalApiKey` from the plugin config.

## 6. Check the result

- The search from step 1 finds nothing, except the lockfile before the next install.
- `hog auth status` shows a login, on the machine and in CI.
- `hog config check` passes when the repository has a `posthog.json`.
- `hog error-tracking process <build output> --dry-run`, or `upload` when the build injects chunk IDs itself, lists the same symbol sets posthog-cli uploaded, and sends nothing.
- The CI job passes, and its upload step lists the symbol sets it uploaded.

## Steps for a person

An agent can't do these. Ask for each one, and say why:

- Approve the browser login from `hog auth login`.
- Approve `hog ci setup` in PostHog. It needs an organization admin.
- Delete `POSTHOG_CLI_API_KEY` from the CI secrets once a run passes with hog.
- Delete the personal API key in PostHog when nothing else uses it.

## What stays the same

- **Your login.** `hog auth migrate` moves the key `posthog-cli login` saved in `~/.posthog/credentials.json` into hog's store. It checks the key with PostHog first, and a key PostHog rejects stays out of hog's store. hog doesn't read that file otherwise and never changes it.
- **Uploads.** hog sends the same bytes and content hashes, so either CLI can re-upload what the other uploaded. Chunk IDs and releases don't change.
- **posthog.json.** hog reads the `languages` entries `posthog-cli exp schema` writes, and the endpoint YAML files `posthog-cli exp endpoints` writes.
- **Global flags.** `--host`, `--dotenv-file`, `--no-fail`, `--skip-ssl-verification` and `--rate-limit` work as before, before or after the command.

## Environment variables

hog reads only `HOG_` variables. Rename these:

| posthog-cli                                    | hog                      |
| ---------------------------------------------- | ------------------------ |
| `POSTHOG_CLI_API_KEY`, `POSTHOG_CLI_TOKEN`     | `HOG_PERSONAL_API_KEY`   |
| `POSTHOG_CLI_PROJECT_ID`, `POSTHOG_CLI_ENV_ID` | `HOG_PROJECT_ID`         |
| `POSTHOG_CLI_HOST`                             | `HOG_HOST`               |
| `POSTHOG_CLI_DOTENV_FILE`                      | `HOG_DOTENV_FILE`        |
| `POSTHOG_CLI_DRY_RUN`                          | `HOG_DRY_RUN`            |
| `POSTHOG_CLIENT_RATE_LIMIT`                    | `HOG_RATE_LIMIT`         |
| `POSTHOG_CLI_SOURCEMAP_UPLOAD_CONCURRENCY`     | `HOG_UPLOAD_CONCURRENCY` |
| `POSTHOG_RELEASE_MODE`                         | `HOG_RELEASE_MODE`       |
| `POSTHOG_HOME`                                 | `HOG_HOME`               |

A dotenv file that `--dotenv-file` names needs the new names too.
In CI, you can set both sets of names while some jobs still run posthog-cli.

## Commands

| posthog-cli                                        | hog                                                                                                            |
| -------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `login`                                            | `auth login`, plus `auth status` and `auth logout`                                                             |
| `update`                                           | `upgrade`                                                                                                      |
| `sourcemap inject --directory <dir>`               | `error-tracking inject <dir>`                                                                                  |
| `sourcemap upload --directory <dir>`               | `error-tracking upload <dir>`                                                                                  |
| `sourcemap process --directory <dir>`              | `error-tracking process <dir>`                                                                                 |
| `hermes inject --directory <dir>`                  | `error-tracking inject <dir>`                                                                                  |
| `hermes clone -m <file1> -c <file2>`               | `error-tracking clone <file1> <file2>`                                                                         |
| `hermes upload --directory <dir>`                  | `error-tracking upload <dir>`                                                                                  |
| `dsym upload --directory <dir>`                    | `error-tracking upload <dir>`                                                                                  |
| `proguard upload --path <file> --map-id <id>`      | `error-tracking upload <file> --map-id <id>`                                                                   |
| `symbol-sets upload --directory <dir>`             | `error-tracking upload <dir>`                                                                                  |
| `symbol-sets download --id <id> -o <dir>`          | `error-tracking download <id> --output-dir <dir>`                                                              |
| `symbol-sets download --ref <ref>`                 | `error-tracking download <ref>`, with `--ref` when the ref looks like an ID                                    |
| `symbol-sets extract <file> -o <dir>`              | `error-tracking extract <file> --output-dir <dir>`                                                             |
| `release resolve`                                  | `error-tracking release -o text`                                                                               |
| `release resolve --json`                           | `error-tracking release -o json`                                                                               |
| `exp query run <query>`                            | `query run <query>`                                                                                            |
| `exp query check <query>`                          | `query check <query>`                                                                                          |
| `exp endpoints list`, `get`, `open`, `run`, `diff` | `endpoints list`, `get`, `open`, `run`, `diff`. `list` shows one page, and `--offset` picks the next           |
| `exp endpoints pull -o <dir>`                      | `endpoints pull --to <dir>`                                                                                    |
| `exp endpoints push`                               | `endpoints push`                                                                                               |
| `exp schema pull -o <file>`                        | `schema pull --file <file>`                                                                                    |
| `exp schema status`                                | `schema status`                                                                                                |
| `api tools`, `search`, `info`, `schema`, `call`    | `api tools`, `search`, `info`, `schema`, `call`, with `-o json` for `--json`                                   |
| `api skill list`, `api skill install <id>`         | `skills list`, `skills add <skill...>`. `add` takes any listed skill and writes to the folder your agent reads |

`hog et` is short for `hog error-tracking`.
`hog error-tracking upload` detects what each path holds, so one command uploads JavaScript, Hermes, ProGuard, dSYM and ELF symbols, and `--kind` skips detection.
Run `hog <command> --help` for every flag, or `hog commands -o json` for all of them at once.

These posthog-cli commands don't come to hog. Remove them from scripts and CI, and tell the person when a repository depends on one:

- `api agents-md`. `hog setup` writes the AGENTS.md note for a project it sets up.
- `exp logs import`, `exp task`, and `exp query editor`.

## Flags that changed

- **Paths are arguments.** `--directory`, `--path`, `-m` and `-c` become positional arguments, and one command takes several paths.
- **`-o` is the output format.** It takes `text` or `json`. posthog-cli's `-o` paths become `--to` in `endpoints pull`, `--file` in `schema pull`, and `--output-dir` in `download` and `extract`.
- **`--stdin` becomes `-`.** `hog error-tracking upload -` and `process -` read one path per line from stdin, like `--stdin` did.
- **`--include` and `--exclude` are gone.** List the paths as arguments, or keep them in `errorTracking.sources` in `posthog.json`, where `ignore` globs skip files.
- **`--skip-release-on-fail` is gone.** hog always retries without the release when PostHog says a chunk belongs to another release, as posthog-cli did.
- **`--main-dsym` is gone.** hog takes the release from `--release-name`, `--release-version`, `--info-plist`, `posthog.json` or git.
- **`--debug` is global.** It prints each request to stderr for every command.

## Dry runs

posthog-cli's `--dry-run` skipped uploads and `release` without doing anything.
hog's `--dry-run` does the work and shows the result without changing anything: uploads list each symbol set with its content hash, and `schema pull`, `endpoints pull` and `push` show what they would change.

`HOG_DRY_RUN=1` turns on `--dry-run` for every command that has one. Commands that only read run as usual.
`auth login` and `auth logout` have no dry run, so they fail when `HOG_DRY_RUN` is set.

## Output

hog prints tables and colors for a person at a terminal, and JSON when an agent runs it, when stdout is a pipe, or with `-o json`.
A script that reads hog's output should pass `-o text` or `-o json`, so the format doesn't depend on where it runs:

```bash
# before
RELEASE_ID=$(posthog-cli release resolve)
# after
RELEASE_ID=$(hog error-tracking release -o text)
```

`posthog-cli exp query run` prints one JSON array per row.
`hog query run -o json` prints one object instead: `columns`, with the name and ClickHouse type of each, `rows`, as arrays in column order, and `hasMore`, which is true when PostHog cut the rows off.
A script that read one row per line reads `.rows` instead:

```bash
# before
posthog-cli exp query run "select event from events" | while read -r row; do echo "$row"; done
# after
hog query run "select event from events" -o json | jq -c '.rows[]' | while read -r row; do echo "$row"; done
```

`--raw` prints PostHog's whole response, as `--debug` did in posthog-cli.

posthog-cli waits for a query until PostHog finishes it.
hog does the same at a terminal and in CI.
An agent or a pipe outside CI waits up to a minute, then gets `{"status":"running","queryId":"<query-id>","next":"hog query run --wait <query-id>"}` and exit code 4.
`hog query run --wait <query-id>` waits for that query again.
A query that joins a run another caller named with an ID beyond letters, digits, `_` and `-` waits until it finishes, as in posthog-cli.

Errors go to stderr, as JSON with a stable `code` in JSON mode.
Each error also names the `hog feedback` command to report it, as a last line for a person and as `feedback` in the JSON. posthog-cli's errors don't.

## Exit codes

posthog-cli exits with 1 for every failure, and with 0 when a check such as `exp endpoints diff` finds a problem.
hog gives each outcome its own code, so a script can tell them apart without reading stderr:

| What happened                                                                                              | posthog-cli | hog |
| ---------------------------------------------------------------------------------------------------------- | ----------- | --- |
| The command worked                                                                                         | 0           | 0   |
| The command failed                                                                                         | 1           | 1   |
| A check found problems: errors in `query check`, drift in `endpoints diff`, a stale SDK in `schema status` | 0           | 1   |
| A usage error                                                                                              | 2           | 2   |
| A person has to act: log in, approve in the browser, add a scope, or answer a question                     | 1           | 3   |
| The work started and is still running. The output names the `--wait` command that resumes it               | Not used    | 4   |

`--no-fail` turns every failure into 0 in both CLIs. In hog that covers 1, 3 and 4. A usage error keeps code 2 in both.
A pipeline that reads exit code 1 as "not logged in" reads 3 with hog.

## posthog.json

hog reads more from `posthog.json` than posthog-cli did: the host, error tracking sources and release, the endpoints folder, and defaults for `--no-fail` and `--rate-limit`.
When the file is invalid, every command stops except `hog config check`, which lists the problems.

posthog-cli rewrites `posthog.json` with only `languages` when it pulls a schema, so it drops hog's settings.
Run only hog's `schema pull` once a project uses hog settings.
