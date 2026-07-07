# Agent platform docs

Concise, diagram-led docs for the v2 agent platform.
Want the 30-second map? Start with **[overview.md](overview.md)** — one diagram of the whole platform.
Want the whole picture on one page? Read **[full-overview.md](full-overview.md)** — an annotated single-page tour of both planes, the request lifecycle, identity, and tool dispatch.
Then read the targeted docs in this order:

1. **[architecture.md](architecture.md)** — the two planes, the data model, the
   spec, and the revision lifecycle. Start here.
2. **[services.md](services.md)** — what each process (ingress, runner, janitor,
   Django) owns and how a request flows through them.
3. **[identity-and-tools.md](identity-and-tools.md)** — edge identity → agent
   user → linked identities → tools, credentials, approvals, and MCP.
4. **[local-dev.md](local-dev.md)** — bringing the stack up locally, driving it,
   and the e2e harness.

Authoritative sources these summarize: `AgentSpecSchema` in
[agent-shared/src/spec/](../services/agent-shared/src/spec/), and the per-service
`AGENTS.md` files under [services/](../services/).
