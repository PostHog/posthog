# Running evals locally and remotely

Use this reference to prepare a machine for the standalone eval harness and choose between local Docker sandboxes and remote Modal sandboxes.
Both providers keep the eval database, Django server, LLM gateway, MCP server, Temporal, personhog, case setup, and scoring on the machine running `hogli evals`.
The provider changes only where the coding-agent sandbox runs.
Prefer remote Modal for multi-case sandboxed evals when its prerequisites are available.
Remote sandboxes run in parallel without consuming local Docker memory, which usually shortens the run substantially.
Use local Docker for a single-case smoke test, offline work, or when Modal and ngrok credentials are unavailable.

## Shared setup

Run evals from the repository root in a flox shell.
The personhog build needs flox's Rust toolchain, `pkg-config`, and OpenSSL.
When a flox shell is not already active, wrap the whole command instead of starting an interactive activation:

```bash
flox activate -- bash -c "hogli evals --list"
```

Use `hogli evals` for normal runs.
It loads the repository's `.env`, `.env.local`, `.env.development`, and `.env.services` files, with existing shell variables taking precedence.
Keep personal credentials in the gitignored `.env.local` or in the shell.
The direct `python -m products.posthog_ai.eval_harness.harness` entry point loads only `.env`, so export any other credentials before using it.

The required variables depend on the selected suite and runtime:

| Selection           | Required variables                                              |
| ------------------- | --------------------------------------------------------------- |
| Every suite         | `BRAINTRUST_API_KEY`, `LLM_GATEWAY_ANTHROPIC_API_KEY`           |
| Any sandboxed suite | `SANDBOX_JWT_PRIVATE_KEY` in addition to the variables above    |
| Codex runtime       | `LLM_GATEWAY_OPENAI_API_KEY` in addition to the variables above |

The local-development sandbox JWT key ships in `.env.example` and is normally copied into `.env` as part of repository setup.
Use that key only for local development, never for production.
Preflight reports every missing variable before it starts the database or any services.

List discovered suite IDs before the first real run:

```bash
hogli evals --list
```

Product-owned suites have IDs in the form `<product>/<module>::<function>`.
Start with one suite and one case so setup errors are cheap to diagnose:

```bash
hogli evals '<product>/eval_example::eval_my_thing' --eval '<case-name>'
```

One-shot-only selections do not use a sandbox provider.
Do not pass `--provider`, `--max-sandboxes`, or other sandbox-only flags for them; preflight rejects those flags rather than ignoring them.

The harness also limits the team-cloning and case-seeding phase separately from sandbox concurrency.
That setup limit is one on an ordinary local machine and automatically increases to four when either `CODER` or `CI` is set.
The higher limit lets managed development and CI environments prepare cases in parallel while keeping local ClickHouse memory use conservative.

## Local setup with Docker

Local sandboxed evals use Docker by default.
Install Docker, start the daemon, and confirm the CLI can reach it:

```bash
docker info
```

No manual sandbox-image build is required.
Before a run, the harness checks whether `posthog-sandbox-base` is current and rebuilds it when the Dockerfile or published agent version changed.
The first personhog build and any required image build can take several minutes; later runs reuse their outputs.

Run one case with one live sandbox first:

```bash
hogli evals '<suite-selector>' \
    --eval '<case-name>' \
    --provider docker \
    --max-sandboxes 1
```

`--provider docker` is optional because Docker is the default.
The default local cap is four concurrent sandboxes, and each sandbox is configured for up to 16 GB of memory.
Keep `--max-sandboxes` low unless the host has enough memory for the requested concurrency.

Normal teardown removes each case's container and sweeps leftovers from the current run.
For a failed case that needs container inspection, rerun it with `--keep-sandbox-containers`; remove the retained container after debugging.
Use `--rebuild-sandbox-image` only when a forced image rebuild is part of the diagnosis.

## Remote setup with Modal (preferred)

Remote sandboxed evals use the dedicated `posthog-sandbox-evals` Modal app.
Install the `modal` and `ngrok` CLIs and make sure both are on `PATH` inside the flox environment.

Authenticate Modal once:

```bash
modal token new
```

This normally writes `~/.modal.toml`.
For non-interactive environments, set both `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` instead.

Authenticate ngrok once:

```bash
ngrok config add-authtoken '<token>'
```

Setting `NGROK_AUTHTOKEN` is the non-interactive alternative.
The harness generates a temporary ngrok configuration and starts HTTPS tunnels for the local Django API, LLM gateway, and MCP server.
Do not manually set `SANDBOX_API_URL`, `SANDBOX_LLM_GATEWAY_URL`, or `SANDBOX_MCP_URL` for an eval run.

The automated Modal provider currently requires three simultaneous ngrok tunnels.
That needs an authenticated paid ngrok plan.
Cloudflare Tunnel can expose the same services in other development workflows, but it is not wired into `hogli evals --provider modal` and does not satisfy the provider's current ngrok preflight.

Start with one remote sandbox to verify credentials, tunnels, and the remote image build:

```bash
hogli evals '<suite-selector>' \
    --eval '<case-name>' \
    --provider modal \
    --max-sandboxes 1
```

The first Modal run builds the eval image remotely.
Later runs reuse that image until its Dockerfile, build context, or bundled local skills change.
Keep the local process and network connection alive because the remote sandbox calls back into the services running on the local machine.

Modal concurrency is unbounded by default, so always choose an intentional `--max-sandboxes` value before running a product or domain with many cases:

```bash
hogli evals '<product-or-domain>' --provider modal --max-sandboxes 4
```

The harness stops its temporary tunnels during teardown.
It also terminates each case's task-tagged sandbox and sweeps leftovers belonging to the current run.
The generated tunnel URLs are publicly reachable while the run is active, so do not share them or leave a run unattended after an interruption.

## Diagnosing setup failures

Read the preflight error first; it names the missing executable, credential, or environment variable and gives the expected fix.
Frequent causes are:

- Running outside flox, which makes the personhog Rust build fail on its toolchain or OpenSSL dependencies.
- A stopped Docker daemon in local mode.
- Missing `~/.modal.toml` or incomplete `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` credentials in remote mode.
- An ngrok free plan or missing authtoken, which prevents all three remote tunnels from starting.
- Passing provider flags to a one-shot-only selection.
- Omitting `LLM_GATEWAY_OPENAI_API_KEY` when selecting `--agent-runtime codex`.

Every real invocation mirrors stdout and stderr to `products/posthog_ai/eval_harness/logs/harness/<timestamp>_<id>.log`.
The final terminal line is that transcript's absolute path, and `logs/harness/latest.log` points to the newest run.
After a case starts, its agent log directory contains `<case>.jsonl`, `<case>.artifacts.json`, and `<case>.summary.txt` for deeper debugging.
