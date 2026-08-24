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

describe("buildGatewayInstallRequest", () => {
  it("builds an oauth install with admin team options", () => {
    const request = buildGatewayInstallRequest(
      values({ description: "  Wiki tools  ", agentIds: ["svc-1"] }),
      { isAdmin: true, canManageAgentAccess: true },
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
      { isAdmin: true, canManageAgentAccess: true },
    );
    expect(request.auth_type).toBe("api_key");
    expect(request.api_key).toBe("sk-123");
  });

  it("includes oauth client credentials only when provided", () => {
    const bare = buildGatewayInstallRequest(values(), {
      isAdmin: true,
      canManageAgentAccess: true,
    });
    expect(bare.client_id).toBeUndefined();
    const withCreds = buildGatewayInstallRequest(
      values({ clientId: " id ", clientSecret: "secret" }),
      { isAdmin: true, canManageAgentAccess: true },
    );
    expect(withCreds.client_id).toBe("id");
    expect(withCreds.client_secret).toBe("secret");
  });

  it("lets permitted members share with agents without team enablement", () => {
    const request = buildGatewayInstallRequest(
      values({ agentIds: ["svc-1"] }),
      { isAdmin: false, canManageAgentAccess: true },
    );
    expect(request.team_enabled).toBeUndefined();
    expect(request.agent_ids).toEqual(["svc-1"]);
  });

  it("omits agent grants when team settings make them admin-only", () => {
    const request = buildGatewayInstallRequest(
      values({ agentIds: ["svc-1"] }),
      { isAdmin: false, canManageAgentAccess: false },
    );
    expect(request.agent_ids).toBeUndefined();
  });
});
