# Running evals locally and remotely

Use this reference to prepare a machine for the standalone eval harness and choose between local Docker sandboxes and remote Modal sandboxes.
Both providers keep the eval database, Django server, LLM gateway, MCP server, Temporal, personhog, case setup, and scoring on the machine running `hogli evals`.
The provider changes only where the coding-agent sandbox runs.
Prefer remote Modal for multi-case sandboxed evals when its prerequisites are available.
Remote sandboxes run in parallel without consuming local Docker memory, which usually shortens the run substantially.
Use local Docker for a single-case smoke test, offline work, or when Modal credentials or a Funnel-capable tailnet are unavailable.

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
| Every suite         | `LLM_GATEWAY_ANTHROPIC_API_KEY`                                 |
| Any sandboxed suite | `SANDBOX_JWT_PRIVATE_KEY` in addition to the variables above    |
| Codex runtime       | `LLM_GATEWAY_OPENAI_API_KEY` in addition to the variables above |

Autoevals judges additionally need `OPENAI_API_KEY`. They use a direct OpenAI client, honoring `OPENAI_BASE_URL` when explicitly configured. Braintrust is used locally and needs no API key.

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
That setup limit is one on an ordinary local machine and automatically increases to two on Coder or four on other CI machines. Use `--team-setup-concurrency` to override it for one run.
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
Install the `modal` and `tailscale` CLIs and make sure both are on `PATH` inside the flox environment.

Authenticate Modal once:

```bash
modal token new
```

This normally writes `~/.modal.toml`.
For non-interactive environments, set both `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` instead.

Connect this machine to your tailnet once:

```bash
tailscale up
```

Funnel additionally needs the `funnel` node attribute granted to the tailnet and this node in the [admin console](https://login.tailscale.com/admin/acls), and HTTPS certificates enabled for the tailnet.
The harness then exposes the local Django API, LLM gateway, and MCP server over Tailscale Funnel for the duration of the run, one service per Funnel public port (`443`, `8443`, `10000`).
Do not manually set `SANDBOX_API_URL`, `SANDBOX_LLM_GATEWAY_URL`, or `SANDBOX_MCP_URL` for an eval run.

Funnel serves only those three public ports, so the harness refuses to start when your tailnet node already serves one of them rather than clobbering it.
Free the port first — `tailscale funnel --https=443 off`, and likewise for `8443` and `10000`.

Start with one remote sandbox to verify credentials, Funnel, and the remote image build:

```bash
hogli evals '<suite-selector>' \
    --eval '<case-name>' \
    --provider modal \
    --max-sandboxes 1
```

The first Modal run builds the eval image remotely.
Later runs reuse that image until its Dockerfile, build context, or bundled local skills change.
Keep the local process and network connection alive because the remote sandbox calls back into the services running on the local machine.

Modal defaults to twelve concurrent sandboxes on Coder and is unbounded elsewhere. Pass an explicit cap to control model spend and load on local services:

```bash
hogli evals '<product-or-domain>' --provider modal --max-sandboxes 4
```

The harness turns its Funnel mappings off during teardown.
It also terminates each case's task-tagged sandbox and sweeps leftovers belonging to the current run.
Funnel config lives in `tailscaled` and outlives the harness process, so a run killed with `SIGKILL` can leave the three ports public — check with `tailscale serve status` and turn them off by hand.
The Funnel URLs are reachable by anyone on the internet who learns them while the run is active, so do not share them or leave a run unattended after an interruption.

## Tuning parallel evals on a Coder devbox

The harness recognizes Coder through `CODER` or `CODER_WORKSPACE_ID`. On the standard devbox it starts with two setup workers and twelve Modal slots. For a large run on a dedicated devbox, size ClickHouse to the available host resources, then measure throughput before raising the per-run concurrency flags. Keep Compose configuration in source control untouched. Local Docker sandboxes draw from the same host memory budget, so use their separate four-slot starting point.

1. Check `nproc`, `free -h`, `df -h .` and `docker stats`. Use the running ClickHouse container's CPU and RAM limits to choose the starting profile. On an idle host with about 16 CPUs and 64 GiB of RAM using Modal, allocate **6 CPUs and 16 GiB to ClickHouse** for the run. Inspect and save the original CPU, memory and swap limits first. Use the actual container name if the Compose project has a different name.

   ```bash
   .codex/with-flox docker inspect --format '{{.HostConfig.NanoCpus}} {{.HostConfig.CpuQuota}} {{.HostConfig.CpuPeriod}} {{.HostConfig.Memory}} {{.HostConfig.MemorySwap}}' posthog-clickhouse-1
   .codex/with-flox docker update --cpus 6 --memory 16g --memory-swap 32g posthog-clickhouse-1
   curl -fsSG http://localhost:8123 --data-urlencode "query=SELECT formatReadableSize(value::UInt64) FROM system.server_settings WHERE name='max_server_memory_usage'"
   ```

   With the standard server ratio of 0.9, wait for the query to report about 14.4 GiB. The run header shows the effective harness limits. Start with the Coder defaults of **2 setup workers and 12 Modal slots**. For a suite with complete fixtures and a persistent setup queue, compare 4 and then 6 workers at the same sandbox cap. A faster event copy alone does not measure full team setup. Compare 12 Modal slots against a neighboring cap on the winning setup configuration. Local Django and MCP latency depend on the suite.

2. Reuse timings from a recent run of the same suite, model, provider and fixture. Otherwise run a representative sample after the master fixture is warm. Include enough trials to fill the candidate sandbox cap and start a second wave. Save each run with a different `--results-file`. Compare completed, correctly seeded trials per minute and total elapsed time.
3. Tune `--team-setup-concurrency` first, keeping the sandbox cap fixed and at least as large as the candidate setup limit. Increase by one worker and compare. Back off when throughput plateaus, ClickHouse hits its memory limit, or setup retries rise. Check the fixture through the same reads the agent relies on, for example the expected experiment chart points and warehouse tables. If cases lose chart points or warehouse tables, rerun with one setup worker and verify the same reads. Django settings overrides such as `TEST` are process-wide and can overlap across worker threads. Additional ClickHouse memory cannot resolve that race. Keep seeding serial for the affected suite until repeated concurrent batches produce complete fixtures. Agent execution can still run in parallel.
4. Fix the best setup count and tune `--max-sandboxes`. A slot covers setup plus execution. Estimate the slots needed as setup workers + (teams prepared per second × average agent seconds), rounded up. For example, four workers preparing a team every 15 seconds collectively and 90-second agents suggest ten slots. Try a neighboring cap with the same sample. Watch local Django and MCP tool latency, timeouts, and delivery of expected tool results as well as model or provider throttling. A faster run that misses required tool behavior is a failed candidate.

Pass the winning pair on the full run. For example, if six workers and twelve slots passed the pilot:

```bash
.codex/with-flox hogli evals '<suite-selector>' --provider modal \
  --team-setup-concurrency 6 --max-sandboxes 12 --trials 20
```

Restore the saved Docker limits when the run finishes, including after a failed pilot. For a container that started at 2 CPUs, 8 GiB RAM and 16 GiB memory-plus-swap, use `.codex/with-flox docker update --cpus 2 --memory 8g --memory-swap 16g posthog-clickhouse-1`. Verify the restored limits with the same checks.

Record the provider, effective ClickHouse limits, worker counts, retries, fixture checks and elapsed time with the result. Reuse the pair for comparable runs and recalibrate when the machine, model or fixture changes.

## Diagnosing setup failures

Read the preflight error first; it names the missing executable, credential, or environment variable and gives the expected fix.
Frequent causes are:

- Running outside flox, which makes the personhog Rust build fail on its toolchain or OpenSSL dependencies.
- A stopped Docker daemon in local mode.
- Missing `~/.modal.toml` or incomplete `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` credentials in remote mode.
- A stopped `tailscaled`, a node that is not logged in, or a tailnet without the `funnel` node attribute or HTTPS certificates, which stops Funnel from serving the three remote-reachable services.
- A Funnel public port (`443`, `8443`, `10000`) already serving something else, which the harness refuses to overwrite.
- Passing provider flags to a one-shot-only selection.
- Omitting `LLM_GATEWAY_OPENAI_API_KEY` when selecting `--agent-runtime codex`.

Every real invocation mirrors stdout and stderr to `products/posthog_ai/eval_harness/logs/harness/<timestamp>_<id>.log`.
The final terminal line is that transcript's absolute path, and `logs/harness/latest.log` points to the newest run.
After a case starts, its agent log directory contains `<case>.jsonl`, `<case>.artifacts.json`, and `<case>.summary.txt` for deeper debugging.
