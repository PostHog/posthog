# Running evals locally and remotely

Use this reference to prepare a machine for the standalone eval harness and choose between local Docker sandboxes and remote Modal sandboxes.
Both providers keep the eval database, Django server, AI gateway, MCP server, Temporal, personhog, case setup, and scoring on the machine running `hogli evals`.
The provider changes only where the coding-agent sandbox runs.
Prefer remote Modal for multi-case sandboxed evals when its prerequisites are available.
Remote sandboxes run in parallel without consuming local Docker memory, which usually shortens the run substantially.
Use local Docker for a single-case smoke test, offline work, or when Modal credentials or a Funnel-capable tailnet are unavailable.
Use a [devbox](#running-on-a-devbox) when a run should not share this machine's databases and ports, or when several runs must go at the same time.

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
| Modal provider      | `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET`, or `~/.modal.toml`   |

The harness reads the provider keys under the `LLM_GATEWAY_` names in the table and hands them to the gateway.
A machine set up for the AI gateway usually holds the same keys as `AI_GATEWAY_ANTHROPIC_API_KEY` and `AI_GATEWAY_OPENAI_API_KEY`, which preflight does not read.
Map them for the run instead of storing a second copy:

```bash
export LLM_GATEWAY_ANTHROPIC_API_KEY="$AI_GATEWAY_ANTHROPIC_API_KEY"
export LLM_GATEWAY_OPENAI_API_KEY="$AI_GATEWAY_OPENAI_API_KEY"
```

Autoevals judges additionally need `OPENAI_API_KEY`. They use a direct OpenAI client, honoring `OPENAI_BASE_URL` when explicitly configured. Braintrust is used locally and needs no API key.

The local-development sandbox JWT key ships in `.env.example` and is normally copied into `.env` as part of repository setup.
Use that key only for local development, never for production.
Preflight reports every missing variable before it starts the database or any services.

Sandboxed suites also need a clone of [`PostHog/ai-gateway`](https://github.com/PostHog/ai-gateway) and `go` on `PATH`, because the harness builds and starts the gateway from that clone.
Clone it wherever suits the machine and point `AI_GATEWAY_REPO` at it:

```bash
git clone git@github.com:PostHog/ai-gateway.git ~/ai-gateway
export AI_GATEWAY_REPO=~/ai-gateway
```

Without `AI_GATEWAY_REPO` the harness looks in `~/Development/ai-gateway`, a directory that a devbox or a fresh machine does not have.
Keep the clone on a recent `main`.
The harness and the gateway change together, so an old clone or a feature branch can refuse every model request or fail its ledger migration.
The [AI gateway section of the harness README](../../../../products/posthog_ai/eval_harness/README.md#ai-gateway) covers its database and test credits.

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
The `modal` CLI comes with the repository's Python environment, so it is on `PATH` inside flox.
Install `tailscale` on the machine yourself.
On Linux, the [install script](https://tailscale.com/download/linux) adds the package and starts `tailscaled`:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
```

Authenticate Modal once:

```bash
modal token new
```

This normally writes `~/.modal.toml`.
For non-interactive environments, set both `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` instead.

Connect this machine to your tailnet once.
On Linux, also make your user the operator, so the harness can change Funnel config without `sudo`:

```bash
sudo tailscale up
sudo tailscale set --operator="$USER"
```

`tailscale up` prints a login URL, so ask the user to run it in their own terminal.

Funnel additionally needs the `funnel` node attribute granted to the tailnet and this node in the [admin console](https://login.tailscale.com/admin/acls), and HTTPS certificates enabled for the tailnet.
The harness then exposes the local Django API, AI gateway, and MCP server over Tailscale Funnel for the duration of the run, one service per Funnel public port (`443`, `8443`, `10000`).
Do not manually set `SANDBOX_API_URL`, `SANDBOX_AI_GATEWAY_URL`, or `SANDBOX_MCP_URL` for an eval run.

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

## Running on a devbox

A devbox is a remote workspace that can host the whole harness.
Use the `setting-up-devbox` skill to get one and to connect to it; this section covers what an eval run adds.

Run one harness per machine:

- The harness keeps its eval databases between runs, and a machine has one set of them, so two runs on one machine write to the same databases.
- Funnel has three public ports per node, and one Modal run takes all three.

So to run several suites, models or prompt variants at once, give each run its own box.
Inside one run, `--max-sandboxes` sets how many cases run in parallel.

### Prepare a box

Start a labeled box for each concurrent run:

```bash
hogli devbox:start -n evals-a
```

Then set the box up once:

1. Put the branch under test in `~/posthog` on the box. Check it out there, or mirror a local checkout with `hogli devbox:sync`.
2. Clone `PostHog/ai-gateway` on the box, as [shared setup](#shared-setup) describes.
3. For Modal, check `tailscale status` on the box. When the command is missing or the node is logged out, follow [remote setup with Modal](#remote-setup-with-modal-preferred) on the box. The login step is interactive, so ask the user to run it through `hogli devbox:ssh -n evals-a`.
4. The box's node needs the `funnel` attribute and HTTPS certificates, as that section describes.

`hogli devbox:clone -n evals-a --as <label>` copies the prepared box, including its eval databases and any secrets on it, so later boxes skip steps 1 and 2.
Keep `-n evals-a`: without a source, the command copies the default box instead.
It asks for confirmation; pass `-y` only after the user agrees.

A clone also copies the source's Tailscale node identity, so both boxes would answer as the same node on the same Funnel hostname and steal each other's callbacks.
`tailscale status` looks healthy on such a clone, so it does not show the problem.
Before a clone's first Modal run, give it its own identity by removing the copied state and logging in again:

```bash
sudo systemctl stop tailscaled
sudo rm /var/lib/tailscale/tailscaled.state
sudo systemctl start tailscaled
sudo tailscale up
sudo tailscale set --operator="$USER"
```

Do not run `tailscale logout` on the clone, because the identity it would log out is the one the source box still uses.

### Lend credentials

Do not copy keys into files on the box.
`hogli devbox:secrets:push` lends the `op://` references in `~/.config/posthog/devbox-secrets.env` to a box, in memory and for 12 hours by default:

```bash
hogli devbox:secrets:push -n evals-a
```

The file needs the variables from the [shared setup table](#shared-setup) for the suites and runtime you run.
On the box, wrap the command that needs them in `devbox-secrets run -- <command>`.

### Run and read results

`hogli devbox:exec` runs one command over SSH.
`--flox` runs it in `~/posthog` inside the flox environment, which the harness needs:

```bash
hogli devbox:exec -n evals-a --flox -- bash -c \
    "devbox-secrets run -- hogli evals '<suite-selector>' --provider modal --no-tui"
```

A run that outlives the SSH session should be started detached, with `nohup` or in `tmux`.
A dropped connection otherwise ends the run, and can leave its Funnel ports public.
Follow a detached run through its transcript:

```bash
hogli devbox:exec -n evals-a -- bash -lc \
    'tail -n 40 ~/posthog/products/posthog_ai/eval_harness/logs/harness/latest.log'
```

Scores and agent logs stay on the box under `products/posthog_ai/eval_harness/logs/`.
Read each case's `<case>.summary.txt` there, or copy the run directory back before stopping the box.

### Clean up

- Each run adds teams and events to the box's databases. Check free space with `hogli devbox:cleanup:disk -n evals-a --dry-run` before a large run.
- After an interrupted Modal run, check `tailscale serve status` on the box and turn any leftover Funnel port off.
- `hogli devbox:stop -n evals-a` keeps the disk and stops billing.

## Diagnosing setup failures

Read the preflight error first; it names the missing executable, credential, or environment variable and gives the expected fix.
Frequent causes are:

- Running outside flox, which makes the personhog Rust build fail on its toolchain or OpenSSL dependencies.
- A stopped Docker daemon in local mode.
- Missing `~/.modal.toml` or incomplete `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` credentials in remote mode.
- A stopped `tailscaled`, a node that is not logged in, or a tailnet without the `funnel` node attribute or HTTPS certificates, which stops Funnel from serving the three remote-reachable services.
- A Funnel public port (`443`, `8443`, `10000`) already serving something else, which the harness refuses to overwrite.
- A Linux user that is not the Tailscale operator, which makes the harness's Funnel commands fail with an access error.
- A missing `PostHog/ai-gateway` clone, or one that is far behind `main`.
- A full disk, which makes ClickHouse refuse writes during case setup.
- Passing provider flags to a one-shot-only selection.
- Omitting `LLM_GATEWAY_OPENAI_API_KEY` when selecting `--agent-runtime codex`.

Every real invocation mirrors stdout and stderr to `products/posthog_ai/eval_harness/logs/harness/<timestamp>_<id>.log`.
The final terminal line is that transcript's absolute path, and `logs/harness/latest.log` points to the newest run.
After a case starts, its agent log directory contains `<case>.jsonl`, `<case>.artifacts.json`, and `<case>.summary.txt` for deeper debugging.
