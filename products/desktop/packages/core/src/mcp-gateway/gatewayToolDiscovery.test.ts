import type {
  McpGatewayServer,
  McpGatewayYourConnection,
} from "@posthog/api-client/posthog-client";
import { describe, expect, it, vi } from "vitest";
import {
  discoverGatewayTools,
  findGatewayServer,
  shouldDiscoverGatewayTools,
  usableInstallationId,
} from "./gatewayToolDiscovery";

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

function server(overrides: Partial<McpGatewayServer> = {}): McpGatewayServer {
  return {
    id: "srv-1",
    name: "Linear",
    url: "https://mcp.linear.app/sse",
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

function client(servers: McpGatewayServer[]) {
  return {
    getMcpGatewayServers: vi.fn().mockResolvedValue(servers),
    refreshMcpInstallationTools: vi.fn().mockResolvedValue([]),
  };
}

describe("findGatewayServer", () => {
  const servers = [
    server({ id: "srv-1", template_id: "linear", url: "https://a.example" }),
    server({
      id: "srv-2",
      template_id: null,
      url: "https://b.example/",
      your_connection: connection({ installation_id: "inst-2" }),
    }),
  ];

  it.each([
    ["by id", { serverId: "srv-2" }, "srv-2"],
    ["by installation", { installationId: "inst-2" }, "srv-2"],
    ["by template", { templateId: "linear" }, "srv-1"],
    ["by url", { url: "https://b.example" }, "srv-2"],
    [
      "by url ignoring a trailing slash",
      { url: "https://a.example/" },
      "srv-1",
    ],
    [
      "falls back to url when the template misses",
      { templateId: "unknown", url: "https://b.example" },
      "srv-2",
    ],
  ])("matches %s", (_label, match, expected) => {
    expect(findGatewayServer(servers, match)?.id).toBe(expected);
  });

  it.each([
    ["nothing matches", { serverId: "missing" }],
    ["no match criteria", {}],
  ])("returns null when %s", (_label, match) => {
    expect(findGatewayServer(servers, match)).toBeNull();
  });
});

describe("usableInstallationId", () => {
  it.each([
    ["a connected credential", connection(), "inst-1"],
    ["a self-disabled connection", connection({ is_enabled: false }), "inst-1"],
    ["a pending oauth connection", connection({ pending_oauth: true }), null],
    ["a stale connection", connection({ needs_reauth: true }), null],
    ["no connection", null, null],
  ])("resolves %s", (_label, your_connection, expected) => {
    expect(usableInstallationId(server({ your_connection }))).toBe(expected);
  });

  it("returns null without a server", () => {
    expect(usableInstallationId(null)).toBeNull();
  });
});

describe("shouldDiscoverGatewayTools", () => {
  it.each([
    ["an empty catalog and a live connection", 0, connection(), true],
    ["an already-populated catalog", 12, connection(), false],
    ["no usable connection", 0, connection({ needs_reauth: true }), false],
  ])("is %s -> %s", (_label, tool_count, your_connection, expected) => {
    expect(
      shouldDiscoverGatewayTools(server({ tool_count, your_connection })),
    ).toBe(expected);
  });
});

describe("discoverGatewayTools", () => {
  it("lists tools through the caller's fresh connection", async () => {
    const api = client([server({ your_connection: connection() })]);

    const result = await discoverGatewayTools(api, { serverId: "srv-1" });

    expect(api.refreshMcpInstallationTools).toHaveBeenCalledWith("inst-1");
    expect(result).toEqual({
      serverId: "srv-1",
      installationId: "inst-1",
      discovered: true,
    });
  });

  it("re-reads the registry so a just-created row is visible", async () => {
    const api = client([
      server({ template_id: "linear", your_connection: connection() }),
    ]);

    await discoverGatewayTools(api, { templateId: "linear" });

    expect(api.getMcpGatewayServers).toHaveBeenCalledTimes(1);
  });

  it("uses a caller-supplied registry snapshot instead of re-reading", async () => {
    const api = client([]);
    const servers = [server({ your_connection: connection() })];

    const result = await discoverGatewayTools(
      api,
      { serverId: "srv-1" },
      { servers },
    );

    expect(api.getMcpGatewayServers).not.toHaveBeenCalled();
    expect(result.discovered).toBe(true);
  });

  it.each([
    ["no-server", [], { serverId: "missing" }],
    ["no-connection", [server()], { serverId: "srv-1" }],
    [
      "already-populated",
      [server({ tool_count: 9, your_connection: connection() })],
      { serverId: "srv-1" },
    ],
  ])("skips with %s", async (skipped, servers, match) => {
    const api = client(servers);

    const result = await discoverGatewayTools(api, match);

    expect(result.discovered).toBe(false);
    expect(result.skipped).toBe(skipped);
    expect(api.refreshMcpInstallationTools).not.toHaveBeenCalled();
  });
});
