# The Posthog CLI

```bash
> posthog-cli --help
The command line interface for PostHog 🦔

Usage: posthog-cli [OPTIONS] <COMMAND>

Commands:
  login      Interactively authenticate with PostHog, storing a personal API token locally. You can also use the environment variables `POSTHOG_CLI_TOKEN`, `POSTHOG_CLI_ENV_ID` and `POSTHOG_CLI_HOST`
  capture    Capture an event to PostHog
  exp        Experimental commands, not quite ready for prime time
  sourcemap  Upload a directory of bundled chunks to PostHog
  help       Print this message or the help of the given subcommand(s)

Options:
      --host <HOST>  The PostHog host to connect to [default: https://us.posthog.com]
  -h, --help         Print help
  -V, --version      Print version
```

## Capturing Events

You can capture events to PostHog from the command line using the `capture` command:

```bash
# Capture a simple event
posthog-cli capture --event "user_signup"

# Capture an event with a distinct ID
posthog-cli capture --event "button_clicked" --distinct-id "user123"

# Capture an event with properties using JSON
posthog-cli capture --event "purchase_completed" --distinct-id "user123" --properties '{"amount": 99.99, "currency": "USD"}'

# Capture an event with properties using key=value pairs
posthog-cli capture --event "page_viewed" --distinct-id "user123" --property page=/home --property referrer=google

# Combine JSON and key=value properties
posthog-cli capture --event "complex_event" --properties '{"nested": {"key": "value"}}' --property simple_key=simple_value
```

### Capture Command Options

- `--event` / `-e`: The name of the event to capture (required)
- `--distinct-id` / `-d`: The distinct ID of the user. If not provided, an anonymous event will be captured
- `--properties` / `-p`: Event properties as JSON string (e.g. `'{"key": "value"}'`)
- `--property` / `-P`: Event properties as key=value pairs (can be used multiple times)

## Env-based Authentication

You can authenticate with PostHog interactively for using the CLI locally, but if you'd like to use it in a CI/CD pipeline, we recommend using these environment variables:

- `POSTHOG_CLI_HOST`: The PostHog host to connect to [default: https://us.posthog.com]
- `POSTHOG_CLI_TOKEN`: [A posthog person API key.](https://posthog.com/docs/api#private-endpoint-authentication)
- `POSTHOG_CLI_ENV_ID`: The ID number of the project/environment to connect to. E.g. the "2" in `https://us.posthog.com/project/2`
