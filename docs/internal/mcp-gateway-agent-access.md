# MCP gateway agent access

The MCP gateway exposes a fixed catalog of PostHog agents in **Team and agents**.
Customers do not create, delete, or rotate credentials for agents.

| Agent         | Stable key   | Product availability                   |
| ------------- | ------------ | -------------------------------------- |
| Support agent | `support`    | Support and AI suggestions are enabled |
| Scout agent   | `scout`      | Signals credits are available          |
| PostHog AI    | `posthog_ai` | AI credits are available               |

All three agents also require organization approval for AI data processing.
An unavailable product leaves its agent visible but disabled.
Pausing an available agent is a separate team-controlled setting.

## Connection access

Member and agent access are independent:

- Enabling a gateway server for the team makes it available to members, subject to member-specific revocations and policies.
- Sharing an MCP installation makes its team credential eligible for agent use. It does not grant every agent access.
- An administrator grants or revokes each shared server for each agent explicitly.
- Agents never inherit a member's personal MCP installation or credential.
- Turning member access off does not revoke an explicit agent grant, and turning an agent grant off does not affect members.

Tool policies continue to resolve for the current caller.
Agent-specific policy rows can override the team baseline, while organization guardrails remain authoritative.

## Runtime authorization

Server-owned Support, Scout, and PostHog AI task creation records a trusted agent key in persisted task state.
The public Tasks API cannot claim the reserved origins used by these agents.
A mapped agent task without the matching persisted marker receives no MCP Store connections.

At sandbox boot and refresh, the runtime resolves the persisted task in the expected team and requests only that agent's explicit grants.
The generated connection configuration uses a short-lived signed gateway token and the shared installation credential.
It does not include personal connections or expose the internal task ID to external MCP servers.

Signed gateway tokens are valid for six hours and are checked against the current team, fixed catalog identity, pause state, product settings, and billing availability on every request.
Revoked and cross-team server IDs return not found without contacting an upstream server.

The sandbox's human OAuth token is marked as a built-in-agent token.
That token cannot access the MCP Store member or administration APIs, and it cannot create or control generic tasks.
This prevents an agent from starting a child task that would inherit the backing member's MCP access.

## Rollout

Sandbox OAuth tokens minted before this authorization model do not contain the built-in-agent marker and can live for up to six hours.
Allow that window to drain, or force affected runs to refresh, before treating per-agent isolation as fully enforced.
Existing mapped tasks without trusted persisted provenance fail closed and need a newly created trusted task before MCP Store connections are supplied.
