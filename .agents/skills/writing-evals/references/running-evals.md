# Run evals locally and remotely

Use this reference to prepare the harness and choose a sandbox provider.
Both providers keep databases, Django, the LLM gateway, MCP, Temporal, personhog, setup, and scoring on the machine running `hogli evals`.
The provider changes only where the agent sandbox runs.
Both providers require network access for model calls.

Use Docker for a small local run.
Prefer Modal for larger runs when its prerequisites are available.
Modal runs sandboxes in parallel without using local Docker memory.

## Prepare the shared environment

Run commands from the repository root in a flox shell.
The personhog build needs flox's Rust toolchain, `pkg-config`, and OpenSSL.
For one command, use:

```bash
flox activate -- bash -c "hogli evals --list"
```

`hogli evals` loads `.env`, `.env.local`, `.env.development`, and `.env.services`.
Existing shell variables take precedence.
Keep personal credentials in the gitignored `.env.local` file or in the shell.

The direct entry point is `python -m products.posthog_ai.eval_harness.harness`.
It loads only `.env`. Export credentials from other files before using that entry point.
`hogli evals:sandboxed` is an alias of `hogli evals`.

| Selection                                      | Required variables                                    |
| ---------------------------------------------- | ----------------------------------------------------- |
| Every suite with the current Braintrust engine | `BRAINTRUST_API_KEY`, `LLM_GATEWAY_ANTHROPIC_API_KEY` |
| Any sandboxed suite                            | Also `SANDBOX_JWT_PRIVATE_KEY`                        |
| Codex runtime                                  | Also `LLM_GATEWAY_OPENAI_API_KEY`                     |

Private runners also need these credentials.
Preflight reports missing variables before it starts databases or services.
The local sandbox JWT key is in `.env.example`. Use it only for local development.

List discovered suites before the first run:

```bash
hogli evals --list
```

Choose one suite and one case from the output and source files.
For example:

```bash
hogli evals sql/eval_sql::eval_sql \
    --eval sql_pageviews_by_browser \
    --max-sandboxes 1 \
    --no-tui
```

A run without suite selectors selects every suite.
An unmatched suite selector fails before setup.
One-shot-only selections do not use a sandbox provider.
Do not pass `--provider`, `--max-sandboxes`, or other sandbox-only flags to them. Preflight rejects those flags.

Team copying and seeding have a separate concurrency limit.
The limit is one on ordinary local machines and four when `CODER` or `CI` is set.
Increasing `--max-sandboxes` does not increase this setup limit.

## Use local Docker

Install Docker and start its daemon.
Check access with:

```bash
docker info
```

The harness checks the local `posthog-sandbox-base` image and rebuilds it when required.
It checks the Dockerfile and published agent version. No manual image build is needed.
The first personhog build and sandbox image build can take several minutes.
Later runs reuse their outputs.

Docker is the default provider. To select it explicitly:

```bash
hogli evals sql/eval_sql::eval_sql \
    --eval sql_pageviews_by_browser \
    --provider docker \
    --max-sandboxes 1
```

The default limit is four concurrent sandboxes.
Each sandbox can use up to 16 GB of memory.
Choose a lower limit when the host cannot support that memory use.

Normal cleanup removes case containers and leftovers from the current run.
Use `--keep-sandbox-containers` when you need to inspect a failed case's container.
Remove retained containers after diagnosis.
Use `--rebuild-sandbox-image` only when you need to force an image build.

## Use remote Modal

The remote provider uses the `posthog-sandbox-evals` Modal app.
Install the `modal` and `tailscale` CLIs.
Make sure the flox environment can find both executables.

Authenticate Modal:

```bash
modal token new
```

This normally writes `~/.modal.toml`.
For a non-interactive environment, set both `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET`.

Connect the host to your tailnet:

```bash
tailscale up
```

Tailscale Funnel also needs the `funnel` node attribute and HTTPS certificates for the tailnet.
Configure these in the [Tailscale admin console](https://login.tailscale.com/admin/acls).

The harness exposes Django, the LLM gateway, and MCP through Funnel ports `443`, `8443`, and `10000`.
These URLs are public while the run is active. Do not share them.
Keep the host process and network connection active because remote sandboxes call these local services.

Do not set `SANDBOX_API_URL`, `SANDBOX_LLM_GATEWAY_URL`, or `SANDBOX_MCP_URL` manually for eval runs.
The harness refuses to overwrite an existing service on any required Funnel port.
Check `tailscale serve status` before removing an existing mapping.
For an unused mapping, `tailscale funnel --https=443 off` releases port `443`.
Use the corresponding port for `8443` or `10000`.

Start with one sandbox to check credentials, Funnel, and the image build:

```bash
hogli evals sql/eval_sql::eval_sql \
    --eval sql_pageviews_by_browser \
    --provider modal \
    --max-sandboxes 1
```

The first run builds the Modal image remotely.
Later runs reuse it until its Dockerfile, build context, or bundled local skills change.
Modal has no default concurrency limit. Set an explicit limit for larger selections:

```bash
hogli evals sql --provider modal --max-sandboxes 4
```

Normal cleanup disables Funnel mappings and terminates task-tagged sandboxes from this run.
A `SIGKILL` can leave Funnel mappings active because their configuration lives in `tailscaled`.
After a forced interruption, check `tailscale serve status` and disable the run's remaining mappings.

## Select runtime and skill delivery

Claude is the default agent runtime.
Use `--agent-runtime codex` with `LLM_GATEWAY_OPENAI_API_KEY` to select Codex.
Use `--agent-model <bare-model-id>` to pin the model. Do not include an `anthropic/` or `openai/` prefix.
The runtime and model appear in experiment metadata.

`--skill-delivery bundled` is the default native skill path.
`--skill-delivery exec` tests MCP skill distribution and removes native skills from all cases.
Use separate runs to compare these modes.

## Diagnose setup failures

Read the preflight error first. It names the missing executable, credential, or environment variable.
Common causes include:

- A personhog build outside flox with missing toolchain or OpenSSL dependencies.
- A stopped Docker daemon.
- Missing Modal credentials.
- A stopped or unauthenticated `tailscaled` process.
- Missing Funnel access, HTTPS certificates, or an available Funnel port.
- Sandbox-only flags on a one-shot-only selection.
- Missing OpenAI credentials for the Codex runtime.

The final terminal line gives the full run transcript path.
`logs/harness/latest.log`, under `products/posthog_ai/eval_harness/`, points to the newest transcript.
Open the experiment's `Agent logs` directory for trial summaries, raw agent logs, and artifacts.
See [reading-results.md](reading-results.md) for score meanings, repeated trials, and failure diagnosis.
