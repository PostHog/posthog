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
  -h, --help         Print help
  -V, --version      Print version
```

## Env-based Authentication

You can authenticate with PostHog interactively for using the CLI locally, but if you'd like to use it in a CI/CD pipeline, we recommend using these environment variables:

- `POSTHOG_CLI_HOST`: The PostHog host to connect to [default: https://us.posthog.com]
- `POSTHOG_CLI_API_KEY`: [A posthog personal API key.](https://posthog.com/docs/api#private-endpoint-authentication) (also accepts `POSTHOG_CLI_TOKEN` for backward compatibility)
- `POSTHOG_CLI_PROJECT_ID`: The ID number of the project/environment to connect to. E.g. the "2" in `https://us.posthog.com/project/2` (also accepts `POSTHOG_CLI_ENV_ID` for backward compatibility)

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

## Agent-first API tools

`posthog-cli api` exposes PostHog's MCP tool catalog through a shell-friendly interface for coding agents:

```bash
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
