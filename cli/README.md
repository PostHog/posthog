# The Posthog CLI

```bash
> posthog-cli --help
The command line interface for PostHog 🦔

Usage: posthog-cli [OPTIONS] <COMMAND>

Commands:
  login      Interactively authenticate with PostHog, storing a personal API token locally. You can also use the environment variables `POSTHOG_CLI_TOKEN`, `POSTHOG_CLI_ENV_ID` and `POSTHOG_CLI_HOST`
  query      Run a SQL query against any data you have in posthog. This is mostly for fun, and subject to change
  sourcemap  Upload a directory of bundled chunks to PostHog
  help       Print this message or the help of the given subcommand(s)

Options:
      --host <HOST>  The PostHog host to connect to [default: https://us.posthog.com]
  -h, --help         Print help
  -V, --version      Print version
```

## Env-based Authentication

You can authenticate with PostHog interactively for using the CLI locally, but if you'd like to use it in a CI/CD pipeline, we recommend using these environment variables:

- `POSTHOG_CLI_HOST`: The PostHog host to connect to [default: https://us.posthog.com]
- `POSTHOG_CLI_TOKEN`: [A posthog person API key.](https://posthog.com/docs/api#private-endpoint-authentication)
- `POSTHOG_CLI_ENV_ID`: The ID number of the project/environment to connect to. E.g. the "2" in `https://us.posthog.com/project/2`
