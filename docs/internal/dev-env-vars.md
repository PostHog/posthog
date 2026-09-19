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

`COMPACT_IN_REGION` controls which Cloud region registers the daily AI checkpoint compaction schedule. It defaults to `US`; set it explicitly only when moving the rollout to another region.

See also [sandboxes-setup-guide.md](sandboxes-setup-guide.md) for the PostHog Desktop sandbox providers.

## Local TypeSafe transformation demo

This prototype adds a TypeSafe template to Transformations.
It uses Jev to classify an event and saves the category in an event property.
Use it locally with invented events.
The experimental banner includes a link to contact support if you find an issue.
For TypeSafe, it also explains which event data leaves PostHog and that TypeSafe is not a listed PostHog subprocessor.
It states that the customer's agreements with PostHog, including any DPA, BAA, or MSA, do not cover TypeSafe's processing.
The `typesafe-transformation` feature flag controls template access and creation for each project.
It defaults to off when the flag is missing or cannot be evaluated.
Enable it only for test projects before release.
Turning the flag off hides the template and blocks new transforms, but existing transforms keep running.
Use the transformation's enable switch to stop it.

Start the local stack, then sync the templates so the new template appears in the editor:

```bash
flox activate -- bash -c 'python manage.py sync_hog_function_templates'
```

Drive the demo through the local PostHog UI with Playwright MCP and a signed-in browser session.
No PostHog personal API key is required.

1. Open Data pipelines, then Transformations, and create a TypeSafe transformation.
2. Enter your own TypeSafe API key in the secret **TypeSafe API key** field.
   PostHog stores it with the transformation's encrypted inputs.
   The transform uses this key for each request. It has no shared API key or environment variable fallback.
3. Set the event filters, output property, instructions, categories, and excluded properties.
   The defaults provide an article classification example with `content_category` as the output property.
   Save and enable the transformation.
4. Send invented article events from the browser to the local capture endpoint using the local project's token.
   Include an event outside the filters and an event with a large `debug_blob`.
5. Open the event definitions and set `content_category` as the primary property where no primary property exists.
   This remains a browser setup step for the prototype.
6. Open Activity and filter on `content_category`, then use it as a Trends breakdown.
   Confirm that `debug_blob` remains on the stored event and the event outside the filters has no category.

Exclusions remove matching keys at any depth, or an exact dotted path, from the model input only.
The original event retains those properties.
The request includes the event name and the remaining event properties.
The denylist is not a complete sensitive-data filter.

The native transform waits for the real TypeSafe API with `jev-1.13.0`.
Requests time out after one second.
Each consumer process keeps valid answers in a memory cache of up to 10,000 entries for one hour.
The cache key is the transformation and the full request, so a change to the instructions, categories, or excluded properties does not reuse an old answer.
A cache hit sends no request and adds an info log to the event.
The `cdp.typesafe.cache` counter records each lookup with `outcome` set to `hit` or `miss`.
Uncertain answers, invalid answers, provider failures, and inputs above 16 KB leave the event unchanged.
An existing output property is never overwritten.
Transformation monitoring records request failures without the API key or provider response body.
The PostHog Metrics exporter records each attempted API call in `cdp.typesafe.calls`, with `outcome` set to `success` or `failure`.
It records the call duration, including response parsing, in the `cdp.typesafe.call.duration` histogram in milliseconds.
Skipped calls do not contribute to either metric.
A valid low-confidence answer counts as a successful API call, even when it leaves the event unchanged.
HTTP errors, connection failures, and invalid responses count as failures and go to PostHog Error Tracking.
Error reports contain a fixed message, failure type, and HTTP status when available. They exclude the API key, event properties, provider response body, and original exception.
Metrics use the existing `OTEL_METRICS_EXPORT_URL` and `OTEL_METRICS_EXPORT_TOKEN` settings. Error Tracking uses the existing `POSTHOG_API_KEY` and `POSTHOG_HOST_URL` settings.
The corresponding exporter or client must be configured for records to reach PostHog.
Disable the transformation in the UI to stop classification.
