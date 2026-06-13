# refresh_session not on the relay allowlist (blocks MCP hot-loading)

> **Source:** outstanding_items.md § 8 "refresh_session not on the relay allowlist" (§2.1) · **Locus:** backend — relay serializer + sandbox proxying
> **Effort:** S–M (smaller than the doc's "M" — most plumbing already exists) · **Priority:** Medium (feature-blocking for hot-loading; otherwise dormant) · **Blocks rollout:** No (but blocks the planned MCP hot-loading)
> **Joins:** Standalone backend pass. No sibling plan shares this code locus — the relay serializer (`TaskRunCommandRequestSerializer`) and the sandbox-command service (`agent_command.py`) are touched by nothing else in G1–G9. It is feature-blocking only for the planned MCP hot-loading (04_PROMPTS.md § 5.4); until that ships it is dormant.

## Problem

The browser-facing command relay — `POST /api/projects/{project}/tasks/{task}/runs/{run}/command/` — validates its JSON-RPC `method` against a fixed allowlist. Today that allowlist is `["user_message", "cancel", "close", "permission_response", "set_config_option"]`. It does **not** include `_posthog/refresh_session`. So any client (the Max frontend, an API caller) that POSTs `{"method": "_posthog/refresh_session", ...}` to the relay gets a **400 Bad Request** from DRF's `ChoiceField` validation before the request ever reaches a sandbox.

Meanwhile the in-sandbox agent-server's `/command` HTTP endpoint _does_ accept `_posthog/refresh_session` (it has a dedicated handler that reinitializes the ACP session with a new `mcpServers` list while preserving conversation history). And PostHog cloud already speaks this method to the sandbox — but only **server-side**, from Temporal activities, never through the browser relay.

The planned **MCP hot-loading** feature (04_PROMPTS.md § 5.4) is: when a user installs a new MCP server mid-conversation, the new tools should appear on the next turn without starting a new Run or rebaking the system prompt. The mechanism is exactly `_posthog/refresh_session` carrying an updated `mcpServers` array. Until that method can flow from a user action to the live sandbox, hot-loading cannot ship. The triage doc frames this as "either add it to the relay allowlist (+ sandbox proxying) or route the refresh server-side."

The crux is a **security and trust question**: a `refresh_session` payload carries `mcpServers[].url` and `mcpServers[].headers` — including `Authorization: Bearer <token>` entries. Whoever supplies that array dictates which URLs the sandbox connects to and which bearer tokens it presents. That payload must be built from trusted server state, never accepted verbatim from the browser.

## Current behavior (verified)

All line numbers below were opened and confirmed on 2026-06-13.

**Relay allowlist (the 400 source)** — `products/tasks/backend/serializers.py:1397-1475`:

- `class TaskRunCommandRequestSerializer(serializers.Serializer)` at **`:1397`** (doc said ~:1400, drifted by 3).
- `ALLOWED_METHODS = ["user_message", "cancel", "close", "permission_response", "set_config_option"]` at **`:1400-1406`** (doc's range is correct).
- `method = serializers.ChoiceField(choices=ALLOWED_METHODS, ...)` at **`:1412-1415`** — this is what rejects `_posthog/refresh_session` with a 400.
- `validate(self, attrs)` at **`:1438-1475`** does per-method param validation for `user_message`, `permission_response`, `set_config_option`. No `refresh_session` branch (it can't reach here — the `ChoiceField` rejects first).

**Relay endpoint (how `cancel` is proxied into the sandbox)** — `products/tasks/backend/api.py`:

- The `command` action is at **`:2382`**, decorated with `@validated_request(request_serializer=TaskRunCommandRequestSerializer, ...)` at **`:2356-2375`** and `@action(detail=True, methods=["post"], url_path="command", required_scopes=["task:write"])` at **`:2376-2381`**.
- `user_message` is special-cased (**`:2388-2421`**): it does **not** hit the sandbox directly — it signals the Temporal workflow via `signal_task_followup_message(...)` (**`:2403`**) and returns `{"result": {"queued": True}}`. (This is the `{queued: true}` relay the gaps doc § 4.2.1 describes.)
- Every other allowed method (`cancel`, `close`, `permission_response`, `set_config_option`) is proxied **directly to the sandbox over HTTP** (**`:2423-2502`**): parse `run.state` (**`:2423`**), bail if no `sandbox_url` (**`:2425-2429`**), SSRF-check the URL via `_is_valid_sandbox_url` (**`:2431-2436`**, definition at **`:2504-2531`**), mint a per-user `create_sandbox_connection_token` JWT (**`:2438-2442`**), build the JSON-RPC payload by **copying `method` + `params` straight from the validated request** (**`:2444-2453`**), then `_proxy_command_to_agent_server(...)` (**`:2456-2461`**, definition at **`:2533-2561`**) POSTs to `{sandbox_url}/command`.
- So "how cancel is proxied": client → relay → `ChoiceField` passes → payload `{jsonrpc, method: "cancel"}` is forwarded verbatim → sandbox `/command` → agent-server `case "cancel"`. The relay is a thin verbatim pass-through for non-`user_message` methods. The **only** thing it adds is the connection-token JWT; it does **not** synthesize `params`.

**Server-side refresh path (already exists, never browser-exposed)** — `products/tasks/backend/services/agent_command.py`:

- `REFRESH_SESSION_METHOD = "_posthog/refresh_session"` at **`:27`**.
- `send_refresh_session(task_run, mcp_servers, auth_token=None, timeout=45, refreshed_credentials=None, authorship=None)` at **`:304-337`** — builds `params = {"mcpServers": mcp_servers}` (+ optional `refreshedCredentials`, `authorship`) and calls `send_agent_command(...)`.
- `send_agent_command(...)` at **`:114-245`** does the same SSRF validation (`validate_sandbox_url`, **`:53-81`**), reads `sandbox_url` / `sandbox_connect_token` from `task_run.state` (**`:84-87`**), builds auth headers (**`:90-111`**), and POSTs `{sandbox_url}/command`. This is the service-layer twin of the api.py proxy.
- Callers today are **server-side only**:
  - `products/tasks/backend/temporal/process_task/activities/refresh_sandbox_credentials.py:25-41` — `_notify_agent_server_of_refresh(...)` sends an **empty** `mcpServers` + `refreshedCredentials` after re-injecting git/credentials (a logging-only ping; the agent-server returns early without rebuilding the session — see below).
  - `products/tasks/backend/temporal/process_task/activities/send_followup_to_sandbox.py` — the private helper `_refresh_sandbox_mcp(task_run, scopes, auth_token)` (defined at **`:115`**, called from `send_followup_to_sandbox` at **`:75`**) builds the real `mcpServers` list (PostHog MCP + user MCP installs) at **`:140-160`** and calls `send_refresh_session(...)` with one retry (**`:162`** then **`:180`**); this is the genuine "reinitialize with new tools" path used on follow-up turns. (It is already a function, not loose inline code — the refactor in the steps below extracts its config-assembly body into `utils.py`.) Note the MCP bearer token is minted via `create_oauth_access_token(task, scopes=scopes)` at **`:135`**, and `scopes` arrives as the `posthog_mcp_scopes` activity-input parameter (default `"read_only"`), **not** from `run.state`; only `interaction_origin` is read from `run.state` (`:144`, `:151`).

**Where the `mcpServers` list is built (trusted, server-minted)** — `products/tasks/backend/temporal/process_task/utils.py`:

- `McpServerConfig` dataclass + `to_dict()` at **`:243-249`** (shape: `{type, name, url, headers: [{name, value}]}`).
- `get_user_mcp_server_configs(token, team_id, user_id, *, interaction_origin=None)` at **`:256-294`** — reads the user's MCP-store installations via `get_active_installations(...)` and builds configs with `Authorization: Bearer <token>` + `x-posthog-mcp-consumer` headers. **The token is a server-minted MCP access token, not anything the browser supplies.**
- `get_sandbox_ph_mcp_configs(token, project_id, *, scopes, interaction_origin=None)` at **`:310-335`** — builds the single-exec `posthog` MCP config with project-id / read-only / version headers.

**In-sandbox `/command` handler (confirms what `refresh_session` does sandbox-side)** — `Twig/packages/agent/src/server/agent-server.ts` (the agent-server lives in the separate **Twig** repo, a sibling checkout — not under this repo root; paths below are Twig-relative):

- `app.post("/command", ...)` at **`:463`**; it validates params via `validateCommandParams(...)` (`schemas.ts:123`) then dispatches on `command.method`.
- `case POSTHOG_METHODS.REFRESH_SESSION` / `"posthog/refresh_session"` / `"refresh_session"` at **`:800-829`**: reads `params.mcpServers` (array), `params.refreshedCredentials`, `params.authorship`. **If `mcpServers.length === 0`, it logs the refreshed credentials and returns `{ refreshed: true }` immediately without touching the session.** Otherwise it calls `clientConnection.extMethod(POSTHOG_METHODS.REFRESH_SESSION, { mcpServers })`, which interrupts the current ACP query and resumes with the new server list, preserving history.
- Param schema `refreshSessionParamsSchema = z.object({ mcpServers: mcpServersSchema })` at `schemas.ts:95-97`; `commandParamsSchemas` accepts all three method spellings — `refresh_session`, `posthog/refresh_session`, `_posthog/refresh_session` — at `schemas.ts:116-118`. Each `mcpServers` entry is `{type: "http"|"sse", name, url, headers: [{name, value}]}` (`schemas.ts:21-28`). **Confirmed: the sandbox trusts `url` and `headers` verbatim — including any `Authorization` bearer token.**
- The agent-server replies with JSON-RPC error **`-32002`** if a prompt is in flight (a refresh must be dispatched between turns) — documented in `send_refresh_session`'s docstring (`agent_command.py:312-325`).

**Frontend relay consumers (none today need refresh)** — the Max scene (`frontend/src/scenes/max/sandboxStreamLogic.ts`) does **not** call the tasks `/command/` relay directly. It cancels and answers permission prompts through the posthog_ai conversation layer (`api.conversations.permission(...)` at `sandboxStreamLogic.ts:781`), which in turn delegates to the tasks command path server-side (`products/posthog_ai/backend/message_routing.py:162-194` `cancel()` → `send_cancel(run)`). So the conversation router (`message_routing.py`), not the raw relay, is PostHog AI's entry point for control commands. **The doc cites `frontend/src/scenes/max/sandboxWireTypes.ts`; the real path is `frontend/src/scenes/max/types/sandboxWireTypes.ts`** (the whole wire-type set moved under `types/`).

**Net:** the relay rejects `refresh_session` with a 400, but `refresh_session` is already a fully working, SSRF-guarded, retrying **server-side** capability. The browser has never been able to call it, and — per the trust analysis below — should not be the one to supply its payload.

## Approach

**Recommended: Design (b) — route the refresh server-side; do NOT add `refresh_session` to the relay allowlist.**

Expose an MCP-refresh trigger at the **conversation layer** (`products/posthog_ai`) that takes _no client-supplied `mcpServers`_. The browser says only "my MCP installs may have changed, please re-sync this conversation's sandbox." The server rebuilds the trusted `mcpServers` list from PostHog state (`get_sandbox_ph_mcp_configs` + `get_user_mcp_server_configs`, minting fresh tokens) and calls the existing `send_refresh_session(...)`. The relay serializer is left unchanged.

> **Spec deviation (intentional):** `04_PROMPTS.md § 5.4` and `CLOUD_AGENTS_FRONTEND_SPEC.md § 6.7` describe the browser POSTing the full `mcpServers` array (URLs + headers) straight to `/command/`. Design (b) deliberately overrides that mechanism on security grounds — the browser becomes the _trigger_ only, never the _source_ of the server list. Update those spec sections (or add a note) once (b) ships so the docs and the code agree.

Concretely:

1. Add a `refresh_mcp()` method to `MessageRoutingService` (`products/posthog_ai/backend/message_routing.py`, the class that already hosts `cancel()`), mirroring the existing `cancel()` shape. It resolves `self.conversation.current_run`, guards on terminal/no-run, rebuilds the trusted `mcpServers` list, calls `send_refresh_session(run, mcp_servers, auth_token=...)`, maps `-32002` ("prompt in flight") to a clean "try again between turns" response, and surfaces transport failures as `SandboxCommandError`.
2. Expose it on the posthog_ai conversation viewset as a new detail action (e.g. `POST /api/.../conversations/{id}/refresh_mcp/`), schema-annotated so generated TS types stay correct. The frontend (kea logic) calls it after the user finishes installing/removing an MCP server in the MCP-store UI.
3. Leave `TaskRunCommandRequestSerializer.ALLOWED_METHODS` exactly as-is.

**Why (b) over (a):**

- **Security is the deciding factor.** A `refresh_session` payload is `{mcpServers: [{type, name, url, headers}]}` where `headers` routinely carries `Authorization: Bearer <token>`. The relay forwards `params` **verbatim** (`api.py:2448-2451`) — it does not synthesize them. If we added `refresh_session` to the allowlist and let the relay pass `params` through, the **browser would dictate which URLs the sandbox connects to and which bearer tokens it sends**. That is a credential-injection / SSRF amplification surface: the existing `_is_valid_sandbox_url` check only validates the _sandbox's_ URL, not the _MCP server URLs inside the payload_, which the sandbox connects to directly with no PostHog-side allowlisting. The agent-server trusts `url`/`headers` verbatim (`schemas.ts:21-28`). Server-side routing keeps token-minting and URL selection entirely server-trusted — the browser never names a URL or a token.
- **The plumbing already exists.** `send_refresh_session`, `send_agent_command`, the SSRF guard, the MCP-config builders, and the in-sandbox handler are all shipped and tested. Design (b) reuses them; design (a) would require _new_ server-side validation to re-derive a trustworthy `mcpServers` from an untrusted request anyway — at which point you've done (b)'s work plus exposed a dangerous method.
- **It matches the existing PostHog AI architecture.** Max already routes control commands (`cancel`, `permission_response`) through the conversation layer, not the raw tasks relay. A `refresh_mcp` conversation action is the consistent shape.
- **The relay's verbatim-forward design is load-bearing.** The other allowed methods (`cancel`, `close`, `permission_response`, `set_config_option`) carry only opaque ids/strings the sandbox interprets — none let the browser choose an outbound URL or credential. Keeping `refresh_session` off the allowlist preserves that invariant: the relay never forwards a network destination.

**Rejected — Design (a): add `refresh_session` to the relay allowlist + wire sandbox proxying.** Even with a `validate()` branch enforcing the `mcpServers` shape, the relay would still forward client-chosen URLs and headers verbatim. To make it safe we'd have to _ignore_ the client `params` and rebuild `mcpServers` server-side inside `command()` — which is exactly design (b), but bolted onto a generic relay action that also serves PostHog Code, with worse cohesion and a live footgun if a future edit ever forwarded the client array. The only thing (a) buys is letting PostHog Code reuse the same relay verb; PostHog Code already refreshes MCP via the Temporal `send_followup_to_sandbox` path, so there is no caller that needs the relay verb.

**Note on scope vs. "no client MCP list at all":** § 5.4 explicitly reserves `refresh_session` for "user actions that genuinely add or remove an MCP server at the project level (e.g., installing a new user MCP), not for scene navigation." The user _selects_ which MCP to install through the MCP-store UI (which writes an installation row); the refresh trigger then just re-reads those installations. The browser is the _trigger_, never the _source of truth_ for the server list. That is fully compatible with (b).

## Implementation steps

1. **Add `refresh_mcp()` to `MessageRoutingService`** (`products/posthog_ai/backend/message_routing.py`, next to `cancel()` at `:162`; the class is `MessageRoutingService` at `:101`, constructed as `MessageRoutingService(conversation, user)`):
   - Guard: `conversation.task_id is None` → `ValidationError`; `current_run is None` or `run.is_terminal` → return an idempotent "nothing live to refresh" result (no telemetry, like `cancel()` does at `:176-180`).
   - Mint the MCP OAuth access token (`create_oauth_access_token(task, scopes=...)`, the bearer placed _inside_ the `mcpServers` headers) the same way `send_followup_to_sandbox._refresh_sandbox_mcp` does at `:135`. The transport auth (connection JWT via `create_sandbox_connection_token`) is optional: `cancel()` reaches the sandbox with no `auth_token` (`send_cancel(run)` at `:182`), so a web-layer refresh can do the same unless the run is a Modal-tunnel run that needs the JWT — mirror `cancel()` first and add the JWT only if reachability requires it. Reuse the existing minting helpers; do not hand-roll token minting.
   - Build the trusted list: `mcp_servers = [c.to_dict() for c in get_sandbox_ph_mcp_configs(...) ] + [c.to_dict() for c in get_user_mcp_server_configs(...)]`. **Scopes:** PostHog AI runs are always created with `posthog_mcp_scopes="full"` (`message_routing.py:283/328/395/497`), so the refresh must use `"full"` to match — do **not** default to `"read_only"`. `interaction_origin` is read from `run.state` (`(run.state or {}).get("interaction_origin")`); `scopes` is **not** in `run.state` in `send_followup_to_sandbox` (it arrives as the `posthog_mcp_scopes` activity-input parameter, frozen from the workflow's persisted state — `workflow.py:177`). Factor the config-assembly body of `send_followup_to_sandbox._refresh_sandbox_mcp` (`:140-160`, currently a private function, not loose inline code) into a shared helper in `utils.py` (e.g. `build_sandbox_mcp_servers(task_run, *, token, scopes)`) and call it from both places so the two paths cannot drift.
   - `result = send_refresh_session(run, mcp_servers, auth_token=connection_token)`.
   - Map outcomes: success → return run id/status; `result.error` containing the `-32002` "prompt in flight" signal → raise a typed, retryable error the viewset renders as a clear 409/425-style "agent is mid-turn, retry shortly" (do **not** 500); other failures → `SandboxCommandError` (mirrors `cancel()` at `:183-186`).
   - Keep any irreversible side effects out of a `transaction.atomic` block (there are none here — this is a network call, not a write). No DB transaction needed.

2. **Add the conversation viewset action** (the posthog_ai conversation viewset — locate it under `ee/api/conversation.py` / the posthog_ai routes; the existing `permission` action is the template). Decorate with `@extend_schema` (request + 200/400/409 responses) or `@validated_request` per the `/improving-drf-endpoints` conventions:
   - Request body: minimal — no `mcpServers`. Either an empty body or, if you want forward-compat, a tiny serializer with an optional `reason`/`source` enum for telemetry. Define a `RefreshMcpRequestSerializer` and `RefreshMcpResponseSerializer` (fields: `task_id`, `run_id`, `run_status`, `refresh_requested: bool`) with `help_text` on every field so the generated TS types and any MCP tool schema are correct.
   - `required_scopes` consistent with the other conversation actions; reuse the same object-permission/`get_object()` path so a user can only refresh their own conversation's run (the relay already enforces per-user run ownership — see `test_command_on_other_user_run_returns_404` at `api.py` test `:500`).
   - Guard double-submission server-side by being idempotent (terminal/no-run → 200 no-op).

3. **Regenerate types:** run `hogli build:openapi` so `api.schemas.ts` / `api.ts` / `api.zod.ts` (frontend + `products/tasks` + posthog_ai generated dirs) pick up the new action. Do not hand-edit generated files.

4. **Frontend trigger** (only the kea-logic wiring; the heavy lifting is server-side):
   - In the MCP-store install/uninstall success path, after the installation row is written, call the generated `refreshMcp` API function for the active conversation's run via a kea `listener` in the relevant Max logic. Explicit return types; business logic in the logic, not a React hook (per CLAUDE.md). Guard the trigger against double-submission with a `*Loading` flag wired into the button's `disabledReason`/`loading`.
   - On the "agent mid-turn" (409/425) response, surface a non-blocking toast ("New tools will load after the current turn") and optionally re-attempt once the run reaches an idle status — do not hard-fail.
   - Follow `/adopting-generated-api-types`: import the generated function/types, do not hand-write the request interface.

5. **Leave the relay untouched.** Add a one-line comment near `ALLOWED_METHODS` (`serializers.py:1400`) noting that `refresh_session` is intentionally **not** relay-exposed because its payload carries outbound URLs + bearer headers and is routed server-side via `message_routing.refresh_mcp` → `send_refresh_session`. (Comment explains _why_, per CLAUDE.md.)

## Files to change

| Path                                                                                                                                          | Change                                                                                                                                                                                         |
| --------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `products/posthog_ai/backend/message_routing.py`                                                                                              | New `refresh_mcp()` method on `MessageRoutingService` (server-side trusted refresh).                                                                                                           |
| `products/tasks/backend/temporal/process_task/utils.py`                                                                                       | Extract `build_sandbox_mcp_servers(task_run, *, token, scopes)` helper from the config-assembly body of `send_followup_to_sandbox._refresh_sandbox_mcp` (`:140-160`); call it from both sites. |
| `products/tasks/backend/temporal/process_task/activities/send_followup_to_sandbox.py`                                                         | Replace the MCP-config assembly inside `_refresh_sandbox_mcp` with the new shared helper (no behavior change).                                                                                 |
| posthog_ai conversation viewset (`ee/api/conversation.py` or the posthog_ai presentation layer — locate via the existing `permission` action) | New `refresh_mcp` detail action + `@extend_schema`/`@validated_request` annotations + request/response serializers.                                                                            |
| Generated API types (`frontend/src/generated/core/*`, `products/tasks/frontend/generated/*`, posthog_ai generated dir)                        | Regenerated by `hogli build:openapi` — do not hand-edit.                                                                                                                                       |
| Max MCP-store frontend logic (kea)                                                                                                            | Listener that calls `refreshMcp` after install/uninstall; loading guard + mid-turn toast.                                                                                                      |
| `products/tasks/backend/serializers.py`                                                                                                       | One explanatory comment at `ALLOWED_METHODS` (`:1400`); **no method added**.                                                                                                                   |

## Decisions & open questions

1. **Relay allowlist vs. server-side routing — (a) or (b)?**
   **Recommendation: (b), server-side.** The `refresh_session` payload carries outbound MCP URLs + bearer-token headers that the sandbox trusts verbatim; the relay forwards `params` verbatim, so (a) would let the browser inject network destinations and credentials. (b) reuses the already-shipped, SSRF-guarded server path and matches how Max already routes `cancel`/`permission`. This is the load-bearing decision; everything else follows.

2. **Where does the refresh trigger live — conversation action vs. tasks relay action?**
   **Recommendation: a new posthog_ai conversation action** (`refresh_mcp`), consistent with `cancel`/`permission` already living there. Keeps PostHog AI's control surface in one place and keeps the generic tasks relay free of network-destination-bearing verbs.

3. **What does the request body contain?**
   **Recommendation: no `mcpServers` from the client.** Empty body, or at most an optional `source`/`reason` enum for telemetry. The server is the sole source of the server list. This is the difference between safe and unsafe — make it explicit in the serializer (`help_text` saying the server list is derived server-side).

4. **How to handle "agent is mid-turn" (`-32002`)?**
   **Recommendation:** map it to a distinct, non-500 response (409 Conflict or 425 Too Early) with a clear message, and have the frontend retry once the run goes idle (or show a "tools load after this turn" toast). A refresh must be dispatched between turns (`agent_command.py:312-325`); failing loudly with a 500 would be a worse UX than a soft retry.

5. **Should this also serve PostHog Code (the tasks relay's other consumer)?**
   **Recommendation: no new work.** PostHog Code refreshes MCP via the Temporal `send_followup_to_sandbox` path already; it has no need for a browser-initiated refresh. Scope this to PostHog AI / Max. If PostHog Code later wants a manual UI refresh, it can call the same conversation-layer pattern.

6. **De-dup the MCP-config assembly?**
   **Recommendation: yes** — extract `build_sandbox_mcp_servers(...)` so `refresh_mcp()` and `send_followup_to_sandbox` build the identical trusted list. Two divergent builders is a future correctness bug (the hot-loaded server list must match what a follow-up turn would produce).

## Dependencies & sequencing

- **Within this pass:** (1) the shared `build_sandbox_mcp_servers` helper → (2) `refresh_mcp()` router method → (3) conversation viewset action → (4) `hogli build:openapi` → (5) frontend trigger. Steps 1–3 are pure backend and independently testable; 4 gates 5.
- **Cross-references to sibling plans:** none of G1–G9 touch `agent_command.py`, `message_routing.py`'s command methods, or the relay serializer, so there is no overlap to coordinate. Closest neighbor is **G6 (sandbox notification rendering)**, which renders `_posthog/*` notifications including `resources_used`/`usage`; if hot-loading lands, the tool list visibly changes mid-conversation, so G6's "resources used" bar should be robust to the tool set changing between turns — flag this to the G6 owner but do not duplicate their rendering scope here. **G7 (streaming resilience)** owns SSE reconnect; a `refresh_session` interrupts the ACP query, so confirm with G7 that an in-flight stream survives the interrupt+resume (the agent-server preserves history; the SSE should not be torn down) — verification only, no shared code.
- **External prerequisite:** the MCP-store install/uninstall UI must emit a success event the new frontend listener can hook. Confirm that surface exists before wiring step 5; if it does not yet, ship steps 1–4 (the server capability) and land the frontend trigger when the install UI is ready. Steps 1–4 are independently shippable and unblock the feature server-side.

## Testing

- **Serializer (negative, locks the decision):** a guard test asserting the relay still **rejects** `_posthog/refresh_session` (and `refresh_session`) with a 400, so nobody silently re-exposes it. A sibling guard already exists — `test_command_rejects_posthog_prefixed_methods` at `products/tasks/backend/tests/test_api.py:6165` (it asserts a 400 for `_posthog/user_message`). Extend it (parameterize over `_posthog/refresh_session`, `refresh_session`) rather than writing a duplicate. The command-test class `TestTaskRunCommandAPI` starts at `:5655`.
- **`build_sandbox_mcp_servers` helper (unit):** asserts the assembled list equals PostHog MCP config + user-install configs, with the correct headers and the server-minted token — and that it is byte-identical to what `send_followup_to_sandbox` produces (refactor-equivalence test).
- **`refresh_mcp()` router (unit, mock `send_refresh_session`):** mirror the `cancel()` tests in `products/posthog_ai/backend/test/test_message_routing.py:327+`. Cases: no task → ValidationError; no run / terminal run → idempotent no-op (no `send_refresh_session` call); happy path → `send_refresh_session` called once with the trusted list + a server-minted `auth_token`; `-32002` mid-turn → typed retryable error, not 500; transport failure → `SandboxCommandError`.
- **Viewset action (API test):** `POST /conversations/{id}/refresh_mcp/` happy path (200, expected response shape); another user's conversation → 404 (reuse the ownership pattern verified by `test_command_on_other_user_run_returns_404`, `api.py` test `:500`); mid-turn → 409/425.
- **Sandbox-side parity (already covered in Twig):** `schemas.test.ts:198-232` already asserts the agent-server accepts `_posthog/refresh_session` with `mcpServers` and rejects it without; the `claude-agent.refresh.test.ts` / `codex-agent.refresh.test.ts` suites cover the session-rebuild. No new sandbox tests needed for this pass — only verify (don't modify) that side.
- **Frontend (jest):** logic test that an MCP install-success action fires the `refreshMcp` call once, sets/clears the loading guard in both success and error paths, and shows the mid-turn toast on a 409/425. No new Playwright needed unless the MCP-store UI flow is being built in the same PR.
- **Type drift:** after `hogli build:openapi`, assert no uncommitted generated diff (CI's generated-types check covers this).

## Rollout / flagging

- Gate the **frontend trigger** behind the same feature flag that gates MCP hot-loading / the mid-conversation MCP-store install UI (reuse the existing PostHog AI sandbox rollout flag rather than minting a new one). The **server capability** (`refresh_mcp` action) is harmless when never called — it can ship unflagged; it only acts when a client with a live sandbox run hits it.
- **Telemetry:** emit a capture event when `refresh_mcp` is requested and on each outcome (delivered / mid-turn-deferred / failed), tagged with `run_id`, `task_id`, server count, and outcome — mirroring `sandbox_credentials_refreshed` (`refresh_sandbox_credentials.py:143-155`). In Celery/Temporal contexts use `ph_scoped_capture` per CLAUDE.md; in the synchronous DRF view, normal capture is fine. This lets us watch hot-loading adoption and the mid-turn deferral rate before broad rollout.
- Gradual rollout: enable for internal team first, watch the mid-turn-deferral and delivery-failure rates, then widen.

## Effort & risk

**Refined effort: S–M** (below the doc's "M"). The hard parts — SSRF-guarded transport, the in-sandbox handler, the MCP-config builders, retry — are all already shipped. New work is one router method, one schema-annotated viewset action, a small refactor to de-dup the MCP list builder, and a thin frontend listener.

**Risks:**

- **Re-exposing the method on the relay by mistake.** Mitigated by the negative serializer test and the explanatory comment at `ALLOWED_METHODS`.
- **Trusted-list drift.** If `refresh_mcp` and `send_followup_to_sandbox` build different `mcpServers`, hot-loaded tools won't match follow-up-turn tools. Mitigated by the shared `build_sandbox_mcp_servers` helper + refactor-equivalence test.
- **Mid-turn timing.** A refresh while a prompt is in flight returns `-32002`; if the frontend treats that as a hard failure the UX regresses. Mitigated by the explicit 409/425 mapping + retry-on-idle.
- **Token freshness.** The refresh must mint fresh MCP/connection tokens (not reuse a stale one from run state); reuse the existing minting helpers rather than reading a cached token, matching `send_followup_to_sandbox` / `refresh_sandbox_credentials`.
- **Low blast radius:** the capability is dormant until a client calls it, and it cannot affect non-PostHog-AI runs or the existing relay verbs.
