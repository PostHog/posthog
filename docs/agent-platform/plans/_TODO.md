# Plans queue

Each bullet below is a feature we want to design and write its own plan file for.
Reminder list only — we discuss each one-by-one and produce a dedicated
`<feature>.md` next to this file. Move bullets off this list once their plan
exists.

- [ ] **Sandboxed agent inference for advanced capabilities** (e.g. an agent
      that writes / runs PostHog code on our infrastructure). What we'd need:
      a higher-trust sandbox profile, code-execution tooling, repo access
      semantics, output / artifact channel.

- [ ] **Self-healing agents** — let an agent introspect itself on a cron or
      explicit trigger by reading its own historic sessions (via LLM
      analytics, not the `agent_session` table directly) and proposing
      concrete improvements based on real interactions. What signals does
      LLM analytics need to expose? How does the agent draft + test a
      revision against real-traffic snapshots without burning costs?

- [ ] **Control flows / approval-gated tool use** — extend `AgentSpec` so
      individual tool calls can be marked "requires approval". When the
      model tries to invoke one, the session parks; the approval lands via
      either a PostHog UI flow or an approved MCP path; the session resumes
      with the approved args. Think about scope (per-tool? per-args-pattern?),
      audit, and how this composes with existing `@posthog/meta-ask-for-input`.

- [ ] **Rate limiting of concurrent sessions** — per-team / per-agent cap on
      in-flight sessions, plus a queueing policy for when the cap is hit
      (reject? park? FIFO drain?). Think about how this interacts with
      poison-pill retries and Slack thread continuity.

- [x] ~~**Long-lived "waiting" sessions for explicit resume**~~ — see
      [`long-running-sessions.md`](long-running-sessions.md).

- [ ] **Per-session access elevation** — by default a session is private to
      its initiating principal (strict-principal already enforces this on
      `/send`). When a second user tries to interact (a Slack thread reply
      from someone else, a webhook from a different sender) the platform
      should reject AND post a deterministic elevation surface — a button /
      link to a PostHog UI where the original owner (or an authorized team
      member) can grant access to either the specific other user or
      everyone in the workspace. Think about: ACL shape on the session
      (allowlist of principals? a role grant per workspace?), audit log of
      who elevated and when, revocation, how this flows back into Slack
      ("✓ @other-user can now reply to this thread") and other triggers.
