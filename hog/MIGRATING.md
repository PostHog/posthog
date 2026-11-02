# Moving from posthog-cli to hog

> [!NOTE]
> This guide is a draft. hog isn't published yet, and the guide will move to posthog.com when it is.

hog is version 1 of the PostHog command line. It does what posthog-cli does, with new command names, `HOG_` environment variables, and output that agents can read.
Most moves take three steps: install hog, rename the environment variables, and rewrite each command with the tables below.

## What stays the same

- **Your login.** Both CLIs read and write `~/.posthog/credentials.json`, so `posthog-cli login` works for hog, and `hog auth login` works for posthog-cli.
- **Uploads.** hog sends the same bytes and content hashes, so either CLI can re-upload what the other uploaded. Chunk IDs and releases don't change.
- **posthog.json.** hog reads the `languages` entries `posthog-cli exp schema` writes, and the endpoint YAML files `posthog-cli exp endpoints` writes.
- **Global flags.** `--host`, `--dotenv-file`, `--no-fail`, `--skip-ssl-verification` and `--rate-limit` work as before, before or after the command.

## Environment variables

hog reads only `HOG_` variables. Rename these:

| posthog-cli                                    | hog                      |
| ---------------------------------------------- | ------------------------ |
| `POSTHOG_CLI_API_KEY`, `POSTHOG_CLI_TOKEN`     | `HOG_API_KEY`            |
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

| posthog-cli                                        | hog                                                                          |
| -------------------------------------------------- | ---------------------------------------------------------------------------- |
| `login`                                            | `auth login`, plus `auth status` and `auth logout`                           |
| `sourcemap inject --directory <dir>`               | `error-tracking inject <dir>`                                                |
| `sourcemap upload --directory <dir>`               | `error-tracking upload <dir>`                                                |
| `sourcemap process --directory <dir>`              | `error-tracking process <dir>`                                               |
| `hermes inject --directory <dir>`                  | `error-tracking inject <dir>`                                                |
| `hermes clone -m <file1> -c <file2>`               | `error-tracking clone <file1> <file2>`                                       |
| `hermes upload --directory <dir>`                  | `error-tracking upload <dir>`                                                |
| `dsym upload --directory <dir>`                    | `error-tracking upload <dir>`                                                |
| `proguard upload --path <file> --map-id <id>`      | `error-tracking upload <file> --map-id <id>`                                 |
| `symbol-sets upload --directory <dir>`             | `error-tracking upload <dir>`                                                |
| `symbol-sets download --id <id> -o <dir>`          | `error-tracking download <id> --output-dir <dir>`                            |
| `symbol-sets download --ref <ref>`                 | `error-tracking download <ref>`, with `--ref` when the ref looks like an ID  |
| `symbol-sets extract <file> -o <dir>`              | `error-tracking extract <file> --output-dir <dir>`                           |
| `release resolve`                                  | `error-tracking release -o text`                                             |
| `release resolve --json`                           | `error-tracking release -o json`                                             |
| `exp query run <query>`                            | `query run <query>`                                                          |
| `exp query check <query>`                          | `query check <query>`                                                        |
| `exp endpoints list`, `get`, `open`, `run`, `diff` | `endpoints list`, `get`, `open`, `run`, `diff`                               |
| `exp endpoints pull -o <dir>`                      | `endpoints pull --to <dir>`                                                  |
| `exp endpoints push`                               | `endpoints push`                                                             |
| `exp schema pull -o <file>`                        | `schema pull --file <file>`                                                  |
| `exp schema status`                                | `schema status`                                                              |
| `api tools`, `search`, `info`, `schema`, `call`    | `api tools`, `search`, `info`, `schema`, `call`, with `-o json` for `--json` |

`hog et` is short for `hog error-tracking`.
`hog error-tracking upload` detects what each path holds, so one command uploads JavaScript, Hermes, ProGuard, dSYM and ELF symbols, and `--kind` skips detection.
Run `hog <command> --help` for every flag, or `hog commands -o json` for all of them at once.

Not in hog yet, so keep posthog-cli for them:

- `update`. It becomes `hog upgrade` when hog ships.
- `api skill` and `api agents-md`. They come back as top-level commands.
- `exp logs import`, `exp task`, and `exp query editor`.

hog lists these and prints the posthog-cli command to run instead.

## Flags that changed

- **Paths are arguments.** `--directory`, `--path`, `-m` and `-c` become positional arguments, and one command takes several paths.
- **`-o` is the output format.** It takes `text` or `json`. posthog-cli's `-o` paths become `--to` in `endpoints pull`, `--file` in `schema pull`, and `--output-dir` in `download` and `extract`.
- **`--include`, `--exclude` and `--stdin` are gone.** List the paths as arguments, or keep them in `errorTracking.sources` in `posthog.json`, where `ignore` globs skip files.
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

Errors go to stderr, as JSON with a stable `code` in JSON mode.
Exit codes are 0 on success, 1 when a command fails or reports a problem, and 2 for usage errors.
`--no-fail` turns 1 into 0, and leaves 2 alone.

## posthog.json

hog reads more from `posthog.json` than posthog-cli did: the host, error tracking sources and release, the endpoints folder, and defaults for `--no-fail` and `--rate-limit`.
When the file is invalid, every command stops except `hog config check`, which lists the problems.

posthog-cli rewrites `posthog.json` with only `languages` when it pulls a schema, so it drops hog's settings.
Run only hog's `schema pull` once a project uses hog settings.
