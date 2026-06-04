# The Posthog CLI

```bash
> posthog-cli --help
The command line interface for PostHog 🦔

Usage: posthog-cli [OPTIONS] <COMMAND>

Commands:
  login      Interactively authenticate with PostHog, storing a personal API token locally. You can also use the environment variables `POSTHOG_CLI_API_KEY`, `POSTHOG_CLI_PROJECT_ID` and `POSTHOG_CLI_HOST`
  query      Run a SQL query against any data you have in posthog. This is mostly for fun, and subject to change
  sourcemap  Upload a directory of bundled chunks to PostHog
  exp        Contains a set of experimental commands
  help       Print this message or the help of the given subcommand(s)

Options:
      --host <HOST>  The PostHog host to connect to [default: https://us.posthog.com]
      --dry-run      Skip artifact processing and upload without contacting PostHog or requiring credentials
  -h, --help         Print help
  -V, --version      Print version
```

## Env-based Authentication

You can authenticate with PostHog interactively for using the CLI locally, but if you'd like to use it in a CI/CD pipeline, we recommend using these environment variables:

- `POSTHOG_CLI_HOST`: The PostHog host to connect to [default: https://us.posthog.com]
- `POSTHOG_CLI_API_KEY`: [A posthog personal API key.](https://posthog.com/docs/api#private-endpoint-authentication) (also accepts `POSTHOG_CLI_TOKEN` for backward compatibility)
- `POSTHOG_CLI_PROJECT_ID`: The ID number of the project/environment to connect to. E.g. the "2" in `https://us.posthog.com/project/2` (also accepts `POSTHOG_CLI_ENV_ID` for backward compatibility)

These variables can also be loaded from a dotenv-style file via `--env-file <PATH>` (e.g. `posthog-cli --env-file .env query ...`). The process environment always wins; the file is only consulted if the required variables aren't set. `POSTHOG_CLI_HOST` is only read from the same source that supplied the rest, so a stray host in the file cannot redirect a key supplied by the process env.

Full precedence: CLI args → process env → `--env-file` → `~/.posthog/credentials.json` (from `posthog-cli login`).

## Skipping uploads (dry run)

Pass `--dry-run` before the subcommand (`posthog-cli --dry-run hermes upload ...`), or set `POSTHOG_CLI_DRY_RUN=true`, to turn the upload commands — `sourcemap`, `dsym`, `hermes`, and `proguard` — into a no-op.
The CLI logs that it skipped the upload and exits `0` without contacting PostHog or requiring credentials.
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
| `exp endpoints list/get/pull` | `endpoint:read`                            |
| `exp endpoints push`          | `endpoint:write`, `insight_variable:write` |
| `exp endpoints run`           | `query:read`                               |
| `exp tasks`                   | `task:read`                                |
