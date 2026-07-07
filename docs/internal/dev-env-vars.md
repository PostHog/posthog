# Where local dev environment variables come from

If an env var is set in your shell but you can't find it in any `.env*` file, it is almost certainly coming from **flox**, not dotenv.
This is the layering, highest precedence first.

## The layers

1. **Your shell** — anything you `export` yourself wins over everything below.
2. **flox `[vars]`** (`.flox/env/manifest.toml`) — injected on every `flox activate`, which `direnv` runs automatically via `.envrc` whenever you `cd` into the repo. This is where `DEBUG=1`, `CLICKHOUSE_DATABASE`, and other always-on dev knobs live. These are **not** in any `.env` file, which is why grepping `.env*` for them comes up empty.
3. **`.env.local`** — your personal, gitignored overrides and secrets (`op://` refs auto-resolve via 1Password). Sourced by `bin/start`.
4. **`.env.development`** — committed dev-mode runtime knobs.
5. **`.env.services`** — committed service connection defaults, shared with containers.

`bin/start` sources `.env.local` > `.env.development` > `.env.services` and only sets a var if it is not already in the environment, so flox `[vars]` and your shell take precedence over the dotenv files.
`python manage.py setup_background_agents` additionally appends a few keys (`DEBUG`, `SANDBOX_PROVIDER`, …) to `.env` from `.env.example`.

## Tracing a var

To find where `FOO` is actually coming from:

```bash
# The flox layer (the usual "invisible" source):
grep -n FOO .flox/env/manifest.toml
# The dotenv layers:
grep -n FOO .env .env.local .env.development .env.services .env.example
# What the activated env actually resolves to:
flox activate -- bash -c 'echo "$FOO"'
```

## Developing cloud-only features locally

Cloud-gated code checks `is_cloud()`, which is true when `CLOUD_DEPLOYMENT` is one of `US`, `EU`, `DEV`, or `E2E`.
`DEBUG` is on by default in local dev (flox `[vars]`), and there is a hard guard (`posthog/settings/utils.py`) that refuses to boot with `DEBUG` **and** `CLOUD_DEPLOYMENT` in `US`/`EU`/`DEV` — because `DEBUG` relaxes authentication, so it must never coincide with a real deployed-cloud identity.

The sanctioned way to run local dev "as cloud" is therefore:

```bash
# in .env.local
CLOUD_DEPLOYMENT=E2E
```

`E2E` is treated as cloud by `is_cloud()` and is the one cloud value allowed alongside `DEBUG`.
Do **not** set `CLOUD_DEPLOYMENT=US` and unset `DEBUG` to get around the guard — unsetting `DEBUG` then trips the sandbox-provider guards (`docker` / `MODAL_DOCKER` require `DEBUG`), and you end up playing whack-a-mole between the two.
Code that branches on the literal region (`get_instance_region()`, `region == "US"`) will see `"E2E"`; for region-specific work, override it per-test with `@override_settings(CLOUD_DEPLOYMENT="US")` (tests are exempt from the guard).

See also [sandboxes-setup-guide.md](sandboxes-setup-guide.md) for the PostHog Code sandbox providers.
