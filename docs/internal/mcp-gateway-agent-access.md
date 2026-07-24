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
- By default, members can grant or revoke each server for each agent and control that agent's tool policies.
- An administrator can turn off **Allow members to manage agent access** in Team settings to restrict those changes to administrators.
- Sharing access with an agent delegates the requesting member's personal connection to that agent. It does not make the credential available to other team members.
- If the requesting member has no personal connection, an existing team-shared credential can be delegated instead.
- Agents never inherit a connection automatically. They receive only the exact credential bound to an explicit grant.
- Changing the team setting does not revoke existing grants. It only controls who can add, revoke, or tune them.
- Turning member access off does not revoke an explicit agent grant, and turning an agent grant off does not affect members.

Inbox reads the Scout agent's configured grants rather than the signed-in member's personal connections.
Every project member can see credential-safe server names and readiness states there.
The response never includes installation IDs, credential owners, URLs, or secrets.
Existing grants whose credential was removed stay visible as needing a connection, so an authorized member or administrator can repair or revoke them.

Tool policies continue to resolve for the current caller.
Agent-specific policy rows can override the team baseline, while organization guardrails remain authoritative.

## Runtime authorization

Server-owned Support and Scout task creation records a trusted agent key in persisted task state.
The public Tasks API cannot claim their reserved origins.
A mapped agent task without the matching persisted marker receives no MCP Store connections.

The PostHog AI task tracker creates tasks through the public Tasks API and is allowed to set the `posthog_ai` origin.
That client-set origin is not a trusted agent marker by itself, so those tasks fail closed for per-agent MCP grants until they use the server-owned PostHog AI task path.

At sandbox boot and refresh, the runtime resolves the persisted task in the expected team and requests only that agent's explicit grants.
The generated connection configuration uses a short-lived signed gateway token and the credential bound to the grant.
It does not expose that credential to other members or expose the internal task ID to external MCP servers.

Signed gateway tokens are valid for six hours and are checked against the current team, fixed catalog identity, pause state, product settings, and billing availability on every request.
Revoked and cross-team server IDs return not found without contacting an upstream server.
Catalog and proxy requests share per-agent burst and sustained rate limits that match member MCP proxy requests.
One agent cannot consume another agent's allowance, including when they share an egress IP.

The sandbox's human OAuth token is marked as a built-in-agent token.
That token cannot access the MCP Store member or administration APIs, and it cannot create or control generic tasks.
This prevents an agent from starting a child task that would inherit the backing member's MCP access.

## Rollout

Sandbox OAuth tokens minted before this authorization model do not contain the built-in-agent marker and can live for up to six hours.
Allow that window to drain, or force affected runs to refresh, before treating per-agent isolation as fully enforced.
Existing mapped tasks without trusted persisted provenance fail closed and need a newly created trusted task before MCP Store connections are supplied.
