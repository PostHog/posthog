import { describe, expect, it } from "vitest";
import {
  buildGatewayInstallRequest,
  canSubmitGatewayServer,
  GATEWAY_ADD_SERVER_DEFAULTS,
  type GatewayAddServerValues,
} from "./gatewayAddServer";

function values(
  overrides: Partial<GatewayAddServerValues> = {},
): GatewayAddServerValues {
  return {
    ...GATEWAY_ADD_SERVER_DEFAULTS,
    name: "Internal Wiki",
    url: "https://mcp.example.com/sse",
    ...overrides,
  };
}

describe("canSubmitGatewayServer", () => {
  it.each([
    ["valid name and url", values(), true],
    ["missing name", values({ name: "  " }), false],
    ["invalid url", values({ url: "not-a-url" }), false],
  ])("%s", (_label, input, expected) => {
    expect(canSubmitGatewayServer(input)).toBe(expected);
  });
});

const BOTH_AGENTS = ["svc-1", "svc-2"];

describe("buildGatewayInstallRequest", () => {
  it("builds an oauth install with admin team options", () => {
    const request = buildGatewayInstallRequest(
      values({ description: "  Wiki tools  " }),
      { isAdmin: true, canManageAgentAccess: true, agentIds: ["svc-1"] },
    );
    expect(request).toEqual({
      name: "Internal Wiki",
      url: "https://mcp.example.com/sse",
      description: "Wiki tools",
      auth_type: "oauth",
      team_enabled: true,
      agent_ids: ["svc-1"],
    });
  });

  it("includes the key on api-key installs", () => {
    const request = buildGatewayInstallRequest(
      values({ authType: "api_key", apiKey: "sk-123" }),
      { isAdmin: true, canManageAgentAccess: true, agentIds: [] },
    );
    expect(request.auth_type).toBe("api_key");
    expect(request.api_key).toBe("sk-123");
  });

  it("includes oauth client credentials only when provided", () => {
    const bare = buildGatewayInstallRequest(values(), {
      isAdmin: true,
      canManageAgentAccess: true,
      agentIds: [],
    });
    expect(bare.client_id).toBeUndefined();
    const withCreds = buildGatewayInstallRequest(
      values({ clientId: " id ", clientSecret: "secret" }),
      { isAdmin: true, canManageAgentAccess: true, agentIds: [] },
    );
    expect(withCreds.client_id).toBe("id");
    expect(withCreds.client_secret).toBe("secret");
  });

  it("lets permitted members share with agents without team enablement", () => {
    const request = buildGatewayInstallRequest(values(), {
      isAdmin: false,
      canManageAgentAccess: true,
      agentIds: ["svc-1"],
    });
    expect(request.team_enabled).toBeUndefined();
    expect(request.agent_ids).toEqual(["svc-1"]);
  });

  it.each([
    ["shares with every agent by default", [], BOTH_AGENTS, true, BOTH_AGENTS],
    ["drops the agents turned off", ["svc-2"], BOTH_AGENTS, true, ["svc-1"]],
    ["sends none when all are turned off", BOTH_AGENTS, BOTH_AGENTS, true, []],
    // No catalog means no informed choice was possible, so let the backend
    // apply the same all-agents default instead of asserting an empty list.
    ["omits the field before the catalog loads", [], [], true, undefined],
    [
      "omits the field when sharing is admin-only",
      [],
      BOTH_AGENTS,
      false,
      undefined,
    ],
  ])("%s", (_label, excludedAgentIds, agentIds, canManageAgentAccess, sent) => {
    const request = buildGatewayInstallRequest(values({ excludedAgentIds }), {
      isAdmin: false,
      canManageAgentAccess,
      agentIds,
    });
    expect(request.agent_ids).toEqual(sent);
  });
});
