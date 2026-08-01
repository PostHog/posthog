import type {
  McpGatewayServer,
  McpGatewayYourConnection,
  McpResolvedToolPolicy,
} from "@posthog/api-client/posthog-client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  countGatewayServersByCategory,
  countPoliciesByState,
  defaultAgentGrantPolicy,
  filterCatalogTemplates,
  filterGatewayServers,
  formatAgo,
  formatAuditTime,
  getGatewayConnectionStatus,
  getGatewayRailStatus,
  getGatewayServerRemovalAction,
  isAgentPolicyState,
  isConnectedForYou,
  isPolicyStateAllowedByCeiling,
  normalizeGatewayServerUrl,
  railConnectedServers,
  recommendedCatalogTemplates,
  resolvePolicyStateForScope,
} from "./gatewayServers";

describe("agent tool policies", () => {
  it.each([
    ["approved", true],
    ["needs_approval", false],
    ["do_not_use", true],
  ] as const)("allows %s for agents: %s", (state, expected) => {
    expect(isAgentPolicyState(state)).toBe(expected);
  });

  it("treats approval-gated tools as blocked for agents only", () => {
    expect(resolvePolicyStateForScope("needs_approval", "agent")).toBe(
      "do_not_use",
    );
    expect(resolvePolicyStateForScope("needs_approval", "member")).toBe(
      "needs_approval",
    );
    expect(resolvePolicyStateForScope("needs_approval", "team")).toBe(
      "needs_approval",
    );
  });
});

describe("isPolicyStateAllowedByCeiling", () => {
  it.each([
    ["approved", "needs_approval", false],
    ["needs_approval", "needs_approval", true],
    ["do_not_use", "needs_approval", true],
    ["approved", "do_not_use", false],
    ["needs_approval", "do_not_use", false],
    ["do_not_use", "do_not_use", true],
    ["approved", "approved", true],
    ["approved", null, true],
  ] as const)("%s under a %s ceiling is %s", (state, ceiling, expected) => {
    expect(isPolicyStateAllowedByCeiling(state, ceiling)).toBe(expected);
  });
});

function connection(
  overrides: Partial<McpGatewayYourConnection> = {},
): McpGatewayYourConnection {
  return {
    installation_id: "inst-1",
    is_enabled: true,
    pending_oauth: false,
    needs_reauth: false,
    last_used_at: null,
    ...overrides,
  };
}

function server(overrides: Partial<McpGatewayServer>): McpGatewayServer {
  return {
    id: "srv-1",
    name: "Test",
    url: "https://mcp.example.com",
    description: "",
    category: "dev",
    is_team_enabled: true,
    icon_key: "",
    docs_url: "",
    template_id: null,
    template_auth_type: null,
    tool_count: 0,
    connections: [],
    your_connection: null,
    agents: [],
    revoked_user_ids: [],
    is_revoked_for_you: false,
    created_by: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("railConnectedServers", () => {
  const servers = [
    server({ id: "a", name: "Alpha", your_connection: connection() }),
    server({ id: "b", name: "Beta" }),
    server({ id: "c", name: "Gamma", your_connection: connection() }),
  ];

  it("lists only the servers the caller has connected", () => {
    expect(railConnectedServers(servers, "").map((s) => s.id)).toEqual([
      "a",
      "c",
    ]);
  });

  it("filters by name", () => {
    expect(railConnectedServers(servers, "gam").map((s) => s.id)).toEqual([
      "c",
    ]);
  });
});

describe("filterGatewayServers", () => {
  const servers = [
    server({ id: "a", name: "Linear", description: "Ticket tracker" }),
    server({
      id: "b",
      name: "GitHub",
      description: "Code hosting",
      category: "data",
    }),
    server({ id: "c", name: "Notion", url: "https://mcp.notion.so" }),
  ];

  it("matches name, description and url case-insensitively", () => {
    expect(filterGatewayServers(servers, "TICKET", null)[0]?.id).toBe("a");
    expect(filterGatewayServers(servers, "notion.so", null)[0]?.id).toBe("c");
  });

  it("applies the category chip", () => {
    expect(filterGatewayServers(servers, "", "data").map((s) => s.id)).toEqual([
      "b",
    ]);
  });

  it("combines search and category", () => {
    expect(filterGatewayServers(servers, "linear", "data")).toEqual([]);
  });
});

describe("filterCatalogTemplates", () => {
  const templates = [
    { id: "t1", name: "Linear", description: "Tickets", url: "https://a" },
    { id: "t2", name: "GitHub", url: "https://b", category: "data" },
  ];

  it("matches name/description/url and tolerates missing fields", () => {
    expect(filterCatalogTemplates(templates, "tickets", null)).toEqual([
      templates[0],
    ]);
    expect(filterCatalogTemplates(templates, "https://b", null)).toEqual([
      templates[1],
    ]);
  });

  it("applies the category chip", () => {
    expect(filterCatalogTemplates(templates, "", "data")).toEqual([
      templates[1],
    ]);
  });
});

describe("normalizeGatewayServerUrl", () => {
  it.each([
    ["https://mcp.linear.app/sse/", "https://mcp.linear.app/sse"],
    ["https://mcp.linear.app/sse", "https://mcp.linear.app/sse"],
    ["  https://mcp.linear.app// ", "https://mcp.linear.app"],
  ])("normalizes %s", (input, expected) => {
    expect(normalizeGatewayServerUrl(input)).toBe(expected);
  });
});

describe("recommendedCatalogTemplates", () => {
  const templates = [
    { id: "t1", url: "https://mcp.linear.app/sse" },
    { id: "t2", url: "https://mcp.notion.so/mcp" },
    { id: "t3", url: "https://mcp.stripe.com" },
  ];

  it("excludes templates already materialized by template id", () => {
    const servers = [server({ template_id: "t1", url: "https://elsewhere" })];
    expect(recommendedCatalogTemplates(servers, templates)).toEqual([
      templates[1],
      templates[2],
    ]);
  });

  it("excludes templates matched by trailing-slash-insensitive url", () => {
    const servers = [
      server({ template_id: null, url: "https://mcp.notion.so/mcp/" }),
    ];
    expect(recommendedCatalogTemplates(servers, templates)).toEqual([
      templates[0],
      templates[2],
    ]);
  });

  it("returns every template when the registry is empty", () => {
    expect(recommendedCatalogTemplates([], templates)).toEqual(templates);
  });
});

describe("countGatewayServersByCategory", () => {
  it("tallies per category", () => {
    const counts = countGatewayServersByCategory([
      server({ id: "a", category: "dev" }),
      server({ id: "b", category: "dev" }),
      server({ id: "c", category: "data" }),
    ]);
    expect(counts).toEqual({ dev: 2, data: 1 });
  });
});

describe("isConnectedForYou", () => {
  it.each([
    ["own connection", server({ your_connection: connection() }), true],
    [
      "pending oauth does not count",
      server({ your_connection: connection({ pending_oauth: true }) }),
      false,
    ],
    [
      "connection needing reauth does not count",
      server({ your_connection: connection({ needs_reauth: true }) }),
      false,
    ],
    ["not connected", server({}), false],
  ] as const)("%s", (_label, srv, expected) => {
    expect(isConnectedForYou(srv)).toBe(expected);
  });
});

describe("getGatewayConnectionStatus", () => {
  it.each([
    ["connected", connection(), "connected"],
    ["pending OAuth", connection({ pending_oauth: true }), "pending_oauth"],
    [
      "needs reauthorization",
      connection({ needs_reauth: true }),
      "needs_reauth",
    ],
    [
      "reauthorization takes precedence when both flags are set",
      connection({ pending_oauth: true, needs_reauth: true }),
      "needs_reauth",
    ],
  ] as const)("returns the status for %s", (_label, value, expected) => {
    expect(getGatewayConnectionStatus(value)).toBe(expected);
  });
});

describe("getGatewayRailStatus", () => {
  it.each([
    ["no connection", server({}), null],
    [
      "a usable connection",
      server({ your_connection: connection() }),
      "connected",
    ],
    [
      "a connection pending OAuth",
      server({ your_connection: connection({ pending_oauth: true }) }),
      "pending_oauth",
    ],
    [
      "a connection needing reauthorization",
      server({ your_connection: connection({ needs_reauth: true }) }),
      "needs_reauth",
    ],
    [
      "a self-disabled connection",
      server({ your_connection: connection({ is_enabled: false }) }),
      "self_disabled",
    ],
    [
      "revoked access",
      server({ is_revoked_for_you: true, your_connection: connection() }),
      "revoked",
    ],
    [
      "a team-disabled server",
      server({ is_team_enabled: false, your_connection: connection() }),
      "team_off",
    ],
    [
      "self-disabled outranking the auth states",
      server({
        your_connection: connection({ is_enabled: false, needs_reauth: true }),
      }),
      "self_disabled",
    ],
    [
      "revocation outranking self-disable",
      server({
        is_revoked_for_you: true,
        your_connection: connection({ is_enabled: false }),
      }),
      "revoked",
    ],
    [
      "the team master switch outranking everything",
      server({
        is_team_enabled: false,
        is_revoked_for_you: true,
        your_connection: connection({ is_enabled: false, needs_reauth: true }),
      }),
      "team_off",
    ],
  ] as const)("returns the status for %s", (_label, srv, expected) => {
    expect(getGatewayRailStatus(srv)).toBe(expected);
  });
});

describe("getGatewayServerRemovalAction", () => {
  const gatewayUser = (id: number) => ({
    id,
    uuid: `user-${id}`,
    email: `user-${id}@example.com`,
    hedgehog_config: null,
  });

  // Members never receive `connections` (it is admin-only), so every
  // non-admin case keeps the default empty roster — the real API shape.
  it.each([
    [
      "deletes a personally added custom server",
      server({
        created_by: gatewayUser(1),
        your_connection: connection(),
      }),
      false,
      1,
      "delete_for_you",
    ],
    [
      "disconnects from a custom server added by someone else",
      server({
        created_by: gatewayUser(2),
        your_connection: connection(),
      }),
      false,
      1,
      "disconnect",
    ],
    [
      "disconnects from a custom server with no recorded creator",
      server({
        created_by: null,
        your_connection: connection(),
      }),
      false,
      1,
      "disconnect",
    ],
    [
      "disconnects when the current user is unknown",
      server({
        created_by: gatewayUser(1),
        your_connection: connection(),
      }),
      false,
      null,
      "disconnect",
    ],
    [
      "disconnects from a catalog server",
      server({
        template_id: "template-1",
        created_by: gatewayUser(1),
        your_connection: connection(),
      }),
      false,
      1,
      "disconnect",
    ],
    [
      "deletes a custom server for everyone when requested by an admin",
      server({}),
      true,
      1,
      "delete_for_everyone",
    ],
    [
      "does not delete a catalog server for an admin without a connection",
      server({ template_id: "template-1" }),
      true,
      1,
      null,
    ],
    [
      "returns no action without a personal connection",
      server({}),
      false,
      1,
      null,
    ],
  ] as const)("%s", (_label, srv, isAdmin, currentUserId, expected) => {
    expect(getGatewayServerRemovalAction(srv, isAdmin, currentUserId)).toBe(
      expected,
    );
  });
});

describe("countPoliciesByState", () => {
  it("counts each state, defaulting to zero", () => {
    const policy = (state: McpResolvedToolPolicy["policy_state"]) =>
      ({
        tool_name: "t",
        description: "",
        input_schema: {},
        policy_state: state,
        team_state: null,
        locked: false,
        decided_by: "default",
        rule_name: "",
        rule_description: "",
      }) satisfies McpResolvedToolPolicy;
    expect(
      countPoliciesByState([
        policy("approved"),
        policy("approved"),
        policy("do_not_use"),
      ]),
    ).toEqual({ approved: 2, needs_approval: 0, do_not_use: 1 });
  });

  it("counts approval-gated agent tools as blocked", () => {
    expect(
      countPoliciesByState(
        [
          {
            tool_name: "send_message",
            description: "",
            input_schema: {},
            policy_state: "needs_approval",
            team_state: null,
            locked: false,
            decided_by: "scope",
            rule_name: "",
            rule_description: "",
          },
        ],
        "agent",
      ),
    ).toEqual({ approved: 0, needs_approval: 0, do_not_use: 1 });
  });
});

describe("time formatting", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-21T12:00:00"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("formatAgo renders short relative times", () => {
    expect(formatAgo("2026-07-21T10:00:00")).toBe("2h ago");
    expect(formatAgo("2026-07-21T11:59:50")).toBe("just now");
    expect(formatAgo(null)).toBeNull();
  });

  it("formatAuditTime buckets by local day", () => {
    expect(formatAuditTime("2026-07-21T09:58:00")).toBe("Today 09:58");
    expect(formatAuditTime("2026-07-20T17:22:00")).toBe("Yesterday 17:22");
    expect(formatAuditTime("2026-07-15T09:12:00")).toMatch(/^Jul 15 09:12$/);
  });
});

describe("defaultAgentGrantPolicy", () => {
  it.each([
    ["delete-row", "do_not_use"],
    ["run-migration", "do_not_use"],
    ["send", "do_not_use"],
    ["list-tables", "approved"],
    ["search", "approved"],
  ] as const)("%s → %s", (tool, expected) => {
    expect(defaultAgentGrantPolicy(tool)).toBe(expected);
  });
});
