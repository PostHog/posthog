# Preview ("mocked") mode

## TL;DR — the name is wrong

What the codebase calls **preview mode** (`agent_session.is_preview`,
`$agent_is_preview`, the `aud=agent-ingress.preview` JWT, the
`/preview-token` + `/preview-proxy` endpoints) is really a **mocked
run**: the model loop, system prompt, skills, read tools, and approvals
all run for real — only the surfaces that touch the outside world are
faked.

> **If we were naming this today it would be `is_mocked` / "mocked
> run".** "Preview" reads as "a draft you haven't shipped", which is
> only half the story and actively misleads now that mocked runs work
> against the **live** revision too. The wire/DB names are kept for
> compatibility; prefer "mocked run" in user-facing copy and new code
> comments. This doc is the canonical explanation behind that rename.

## What "mocked" means, precisely

| Surface                                                   | Mocked run                                                    |
| --------------------------------------------------------- | ------------------------------------------------------------- |
| Model loop, prompt, skills, reasoning                     | real                                                          |
| Read-only native tools (`@posthog/query`, `slack-read-*`) | real — hit live data                                          |
| Read-only MCP tools (`readOnlyHint: true`)                | real — hit the live server                                    |
| Write/destructive MCP tools, or **unannotated** ones      | mocked (fail-closed)                                          |
| Custom (sandbox) tools                                    | mocked (no read/write signal to gate on)                      |
| Write natives (`slack-post-message`), webhook delivery    | mocked (synthetic success)                                    |
| Approvals                                                 | real — gated tools still queue; the underlying call is mocked |
| Analytics (`$ai_*`)                                       | real, but tagged `$agent_is_preview: true`                    |

"Reads are real" is the load-bearing property: a mocked run of an agent
that reads customer data reads the **real** data. It is safe because
nothing is written back, not because nothing is touched.

### How write-vs-read is decided

- **Native tools** self-declare: write-side tools call
  `isPreviewSideEffect(ctx, ...)` at the top of `run` and return a
  synthetic result; read tools don't.
- **MCP tools** are classified by the server's
  [tool annotations](https://modelcontextprotocol.io/) — a remote tool
  runs for real in a mocked run only when it advertises
  `readOnlyHint: true`. Writes, destructive ops, and **unannotated**
  tools all fail closed. See `makeMcpTool` in
  [build-agent-tools.ts](../services/agent-runner/src/loop/build-agent-tools.ts)
  and `RemoteMcpTool.annotations` in
  [mcp-clients.ts](../services/agent-runner/src/loop/mcp-clients.ts).
- **Custom tools** have no read/write signal (arbitrary author code in a
  sandbox), so every custom-tool call is suppressed — accepted until
  custom-tool schemas can declare a hint.

## What can be mocked: draft OR live

A run lands in mocked mode in exactly two ways, both decided by
`assertPreviewGate` in
[resolver.ts](../services/agent-ingress/src/routing/resolver.ts):

1. **Non-live revision** (draft/ready). Always mocked, and **always
   requires a valid preview JWT** — routing to unpublished code without
   auth would be a hole.
2. **Live revision + a valid preview JWT.** A mocked run of the live
   agent. The live spec is already publicly invokable, so mocking it
   exposes nothing new; this is the "safely reproduce / debug the live
   agent without re-firing real side effects" path.

A **real production run** is the live revision with **no** token. There
is no way to put a real run into mocked mode after the fact, and no way
to give a non-live revision a real (un-mocked) run.

The preview JWT is short-lived (15 min), HMAC-signed, scoped to
`aud=agent-ingress.preview`, and bound to `(app, rev)` so a captured
token can't be replayed against a different revision.

## How to drive one

Both endpoints live on `AgentApplicationViewSet`
([views.py](../backend/presentation/views.py)) and accept any revision
of the application — draft/ready **or** the live revision.

- **`POST .../agent_applications/<id>/preview-proxy/<rest>?revision_id=<rev>`**
  — Django mints the JWT server-side, forwards to ingress as
  `<slug>-<rev-hex>`, and streams the SSE back. `<rest>` ∈
  `run | send | cancel | listen`. Easiest path; strips caller auth so it
  can't impersonate a specific end user.
- **`POST .../agent_applications/<id>/preview-token/?revision_id=<rev>`**
  — returns `{ token, expires_in, ingress_slug, endpoints, auth }` for
  hitting ingress directly (e.g. carrying a specific identity). Attach
  the token as the `x-agent-preview-token` header (or `?preview_token=`
  for EventSource).

The agent builder exposes both as MCP tools
(`agent-applications-preview-proxy`,
`agent-applications-preview-token-mint`) and knows when to offer a
mocked run — see its `running-mocked-preview-runs` skill.

## Why mocked runs need no approval

The destructive authoring ops (promote / archive / destroy) are
approval-gated because they change production. A mocked run changes
nothing in the outside world by construction, so it carries no approval
gate — it is always safe to run.
