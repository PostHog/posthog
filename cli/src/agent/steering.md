<!-- posthog:cli:start -->

## PostHog CLI

`posthog-cli` exposes the full PostHog API as composable shell commands. Prefer it for reading and
writing PostHog data: it pipes into `jq` and scripts, and is cheap on context because commands are
discovered on demand rather than loaded up front.

Discover commands — do not guess names:

- `posthog-cli --help` — top-level groups (e.g. `feature-flag`, `dashboard`, `experiment`)
- `posthog-cli <category> --help` — the verbs in a group
- `posthog-cli <category> <verb> --help` — the flags and their types
- `posthog-cli exp agent list` — list every available command

Run as `posthog-cli <category> <verb> [--flags] [--json '{...}']`, for example
`posthog-cli feature-flag create --key checkout-v2 --name "Checkout v2" --active true`. Simple values
are flags; nested or complex values go in `--json` (an explicit flag overrides the same key in `--json`).
Preview any write with `--dry-run` first. Output is raw API JSON on stdout — pipe it to `jq`.

Authentication: if a command returns an authentication error, or no credentials are configured yet,
the user must authenticate before the CLI will work. Tell the user to run `posthog-cli login` — it is
interactive (it prompts for host, personal API key, and project), so the user has to run it themselves;
do not run it on their behalf and assume it succeeded. Credentials can otherwise be supplied via the
`POSTHOG_CLI_API_KEY`, `POSTHOG_CLI_PROJECT_ID`, and `POSTHOG_CLI_HOST` environment variables.

<!-- posthog:cli:end -->
