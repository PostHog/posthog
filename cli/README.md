# The Posthog CLI

The command line interface for PostHog. Exposes PostHog's MCP tool catalog through a shell-friendly interface, handles debug symbol uploads for error tracking, and more. For full documentation, see [our CLI docs](https://posthog.com/docs/cli).

## Installation

Install the PostHog CLI with our wizard by running this command:

```bash
npx -y @posthog/wizard@latest cli add
```

If you'd rather not use our wizard, you can install the CLI by running:

```bash
npm install -g @posthog/cli@latest
```

Note: if you are installing the CLI for use with a coding agent, you should follow our [setup for agents](https://posthog.com/docs/cli#setup-for-agents) instructions.

## Usage

```bash
> posthog-cli --help
The command line interface for PostHog 🦔

Usage: posthog-cli [OPTIONS] <COMMAND>

Commands:
  login        Interactively authenticate with PostHog, storing a personal API token locally. You can also use the environment variables `POSTHOG_CLI_API_KEY` and `POSTHOG_CLI_PROJECT_ID`
  exp          Experimental commands, not quite ready for prime time
  sourcemap    Upload a directory of bundled chunks to PostHog
  dsym         Upload Apple dSYM debug symbol files to PostHog
  hermes       Upload hermes sourcemaps to PostHog
  proguard     Upload proguard mapping files to PostHog
  symbol-sets  Upload, download, and manage symbol sets
  release      Look up the release a build belongs to
  api          Agent-first PostHog API tools
  help         Print this message or the help of the given subcommand(s)

Options:
      --host <HOST>              The PostHog host to connect to
      --no-fail                  Disable non-zero exit codes on errors. Use with caution
      --skip-ssl-verification    Skip SSL certificate verification when talking to the PostHog API. Use only with self-signed certificates
      --rate-limit <RATE_LIMIT>  Set the number of requests per minute for the Posthog API Client [env: POSTHOG_CLIENT_RATE_LIMIT=]
      --dotenv-file <PATH>       Load PostHog credentials from this dotenv-style file when not present in the process environment. Prefer this over the `--env-file` alias: the npm package runs the binary through a `node` wrapper, and Node's own built-in `--env-file` flag intercepts that spelling. Also settable as `POSTHOG_CLI_DOTENV_FILE`, for callers that control the environment but not the command line (e.g. an Xcode build phase invoking the iOS SDK's upload-symbols.sh) [env: POSTHOG_CLI_DOTENV_FILE=]
      --dry-run[=<DRY_RUN>]      Skip artifact processing and upload (sourcemap, dSYM, hermes, proguard, release) without contacting PostHog or requiring credentials. Intended for CI gates that bundle to catch regressions but must not (or cannot) upload. Not for release builds. Pass it before the subcommand (`posthog-cli --dry-run hermes upload ...`) or set `POSTHOG_CLI_DRY_RUN`. This is distinct from the `exp endpoints` `--dry-run`, which previews endpoint changes [env: POSTHOG_CLI_DRY_RUN=] [default: false] [possible values: true, false]
  -h, --help                     Print help
  -V, --version                  Print version
```

## Env-based Authentication

You can authenticate with PostHog interactively for using the CLI locally, but if you'd like to use it in a CI/CD pipeline, we recommend using these environment variables:

- `POSTHOG_CLI_HOST`: The PostHog host to connect to [default: https://us.posthog.com]
- `POSTHOG_CLI_API_KEY`: [A posthog personal API key.](https://posthog.com/docs/api#private-endpoint-authentication) (also accepts `POSTHOG_CLI_TOKEN` for backward compatibility)
- `POSTHOG_CLI_PROJECT_ID`: The ID number of the project/environment to connect to. E.g. the "2" in `https://us.posthog.com/project/2` (also accepts `POSTHOG_CLI_ENV_ID` for backward compatibility)

These variables can also be loaded from a dotenv-style file via `--dotenv-file <PATH>` (e.g. `posthog-cli --dotenv-file .env query ...`) or the `POSTHOG_CLI_DOTENV_FILE` environment variable. The process environment always wins; the file is only consulted if the required variables aren't set. `POSTHOG_CLI_HOST` is only read from the same source that supplied the rest, so a stray host in the file cannot redirect a key supplied by the process env.

Full precedence: CLI args → process env → `--dotenv-file` → `~/.posthog/credentials.json` (from `posthog-cli login`).

## Uploading native debug symbols

`posthog-cli symbol-sets upload --directory <dir>` scans a directory for native debug symbols and uploads them so PostHog can symbolicate native stack frames.
A single command handles both desktop/server formats:

- **Linux (ELF):** executables, shared libraries, and `objcopy --only-keep-debug` companions that carry a GNU build id. This branch is cross-platform.
- **macOS (Apple `.dSYM`):** dSYM bundles are packaged through the same path as `posthog-cli dsym upload`. That path shells out to `dwarfdump` (bundled with Xcode), so it only runs on macOS — if `dwarfdump` is missing, the bundle is reported and skipped while any ELF symbols in the same directory still upload.
- **macOS (Mach-O executables):** binaries that embed their own DWARF upload directly, keyed by their `LC_UUID`; universal (fat) binaries upload one symbol set per architecture slice. This branch is cross-platform. It exists mainly for Go, which never produces a dSYM (`dsymutil` reports "no debug symbols in executable") — but note Go compresses the embedded DWARF by default, which symbolication can't read yet, so build with `-ldflags=-compressdwarf=false`. C/Swift/Rust executables normally carry no embedded DWARF; upload their dSYMs instead.

Pass `--include-source` to bundle the referenced source files for richer context around frames.

The standalone `posthog-cli dsym upload` command is unchanged and still recommended for dSYM-only Xcode build phases, where it also reads release and version metadata from each bundle's `Info.plist`.

## Injection rewrites your built files

`posthog-cli sourcemap process` and `posthog-cli sourcemap inject` add a chunk id (and, in event release mode, a release id) to each JavaScript chunk, then write the file back in place.
The bytes on disk change.
Cleanup with `--delete-after` rewrites them again when it strips the `sourceMappingURL` comment.

So any content hash you compute before injection no longer matches the file after it.
This breaks a build step that pins such a hash, and it fails silently:

- **Service worker manifests** — e.g. Angular's `ngsw.json`, which stores a SHA-1 for each prefetched asset. The service worker rejects the changed file and the update never installs.
- **Subresource Integrity (SRI)** — an `integrity` attribute computed before injection stops matching, so the browser blocks the script.
- **Deploy manifests** — any pipeline that pins an asset hash before deploying.

Follow one ordering rule: **inject before you compute hashes, or regenerate the manifest after injecting.**

The CLI logs which files injection rewrote, so watch for that warning.

For Angular's esbuild-based `application` builder, use `@posthog/esbuild-plugin` with `@angular-builders/custom-esbuild`. The plugin registers output filenames before esbuild computes content hashes, and stamps the same filename into source-map metadata. Upload afterward without modifying the built JavaScript:

```bash
ng build --configuration production
posthog-cli sourcemap upload --directory ./dist/<app>/browser
```

Do not run `sourcemap process`, `sourcemap inject`, or `sourcemap upload --delete-after` after that build. See the esbuild plugin README for the Angular builder configuration.

If a project cannot customize its builder, keep using the fallback ordering and regenerate Angular's manifest after injection:

```bash
ng build --configuration production
posthog-cli sourcemap process --directory ./dist/<app>/browser
npx ngsw-config ./dist/<app>/browser ./ngsw-config.json /
```

## Configuring sourcemap upload concurrency

Sourcemap uploads run up to 10 file uploads at a time by default. Set a different positive value with `--concurrency` on `sourcemap upload` or `sourcemap process`:

```bash
posthog-cli sourcemap process --directory ./dist --concurrency 32
```

For build integrations such as `@posthog/nextjs-config`, set `POSTHOG_CLI_SOURCEMAP_UPLOAD_CONCURRENCY` in the build environment instead:

```bash
POSTHOG_CLI_SOURCEMAP_UPLOAD_CONCURRENCY=32 npm run build
```

The CLI flag takes precedence over the environment variable. Both require a value greater than zero. This setting applies only to plain sourcemap uploads; other CLI concurrency remains unchanged.

## Resolving a release

`posthog-cli release resolve` prints the id of the release the current build belongs to, creating the release if it doesn't exist yet.
The upload commands do this for you, so reach for it when something else needs the id: a bundler plugin that injects the release into your chunks itself, or a deploy script that wants to record which release it shipped.

```bash
posthog-cli release resolve --release-name my-app --release-version 1.4.0
01a0002e-93b5-0000-24cf-fc02638acd46
```

Only the id goes to stdout, so `RELEASE_ID=$(posthog-cli release resolve)` works.
Pass `--json` to get the whole release, including its hash id and the version that git or CI metadata filled in.

Both `--release-name` and `--release-version` are read from git or CI metadata when you leave them out.
When neither the flags nor that metadata identify a release, the command prints nothing (or `null` with `--json`) and exits `0`, so a build can carry on without one.
A failed lookup exits non-zero instead.

Add `--build` to give a build number its own release: it is packed into the version, so `--release-version 1.4.0 --build 42` resolves to a different release than `--release-version 1.4.0` alone.

Pass `--info-plist <path>` to read the release name, version, and build from `CFBundleIdentifier`, `CFBundleShortVersionString`, and `CFBundleVersion`.
The CLI resolves exact Xcode build-setting references such as `$(APP_VERSION)` and `${BUILD_NUMBER}` from the environment.
Missing, unresolved, or compound values fall back to `PRODUCT_BUNDLE_IDENTIFIER`, `MARKETING_VERSION`, and `CURRENT_PROJECT_VERSION`.
Explicit `--release-name`, `--release-version`, and `--build` values take precedence.

## Skipping uploads (dry run)

Pass `--dry-run` before the subcommand (`posthog-cli --dry-run hermes upload ...`), or set `POSTHOG_CLI_DRY_RUN=true`, to turn the upload commands — `sourcemap`, `dsym`, `hermes`, and `proguard` — into a no-op.
`release resolve` is skipped too, since resolving a release can create one.
The CLI logs what it skipped and exits `0` without contacting PostHog or requiring credentials.
(This top-level flag is separate from the `exp endpoints` `--dry-run`, which previews endpoint changes.)

This is meant for CI gates that still want to run the bundling step (to catch Metro/Hermes or sourcemap regressions) but must not — or cannot — upload artifacts, for example pull-request checks that don't have PostHog credentials.
Do not use it for release builds, since no symbols are uploaded.

The env var accepts the usual truthy/falsy values (`true`/`false`, `1`/`0`, `yes`/`no`, `on`/`off`).

### Personal API key scopes

Commands require different API scopes. Make sure to set these scopes on your personal API key:

| Command                       | Required Scopes                            |
| ----------------------------- | ------------------------------------------ |
| `query`                       | `query:read`                               |
| `sourcemap`                   | `error_tracking:write`                     |
| `symbol-sets`                 | `error_tracking:write`                     |
| `dsym`                        | `error_tracking:write`                     |
| `release`                     | `error_tracking:write`                     |
| `exp endpoints list/get/pull` | `endpoint:read`                            |
| `exp endpoints push`          | `endpoint:write`, `insight_variable:write` |
| `exp endpoints run`           | `query:read`                               |
| `exp tasks`                   | `task:read`                                |

## Agent-first API tools

`posthog-cli api` exposes PostHog's MCP tool catalog through a shell-friendly interface for coding agents:

```bash
posthog-cli api --agent-help
posthog-cli api search feature-flag
posthog-cli api info feature-flag-get-all
posthog-cli api schema query-trends series
posthog-cli api call --json feature-flag-get-all '{"limit":5}'
posthog-cli api call --dry-run feature-flags-bulk-delete-create '{"ids":[123]}'
posthog-cli api skill list
posthog-cli api skill install audit
posthog-cli api agents-md install
```

Destructive tools require `--confirm` when executed. Use `--dry-run` before mutations.

`posthog-cli api --agent-help` prints the full agent-facing guide — the same exec tool reference the PostHog MCP server serves, rewritten for CLI invocation — so agents can load it into context before interacting with PostHog APIs.

### Agent steering instructions

Install the PostHog CLI steering instructions into the agent instructions file for your project:

```bash
posthog-cli api agents-md install
```

By default this updates `AGENTS.md` in the current directory. If your agent reads a different instructions file, pass it explicitly:

```bash
posthog-cli api agents-md install --path path/to/AGENTS.md
```

The installed instructions come from the shared snippet at [`services/mcp/src/cli/agents-md-snippet.md`](../services/mcp/src/cli/agents-md-snippet.md), so the installer and this README point at the same source of truth.

The snippet is written as a `<posthog>...</posthog>` block. Rerunning the install replaces the existing block in place, so upgrading the CLI and reinstalling refreshes stale instructions without duplicating them.
