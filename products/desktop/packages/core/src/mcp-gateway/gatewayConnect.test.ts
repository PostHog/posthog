import { describe, expect, it, vi } from "vitest";
import type {
  InstallFlowClient,
  IOAuthCallback,
} from "../mcp-servers/installFlow";
import {
  canSubmitGatewayConnect,
  connectGatewayServer,
  GATEWAY_CONNECT_DEFAULTS,
  type GatewayConnectCredentials,
  gatewayConnectAuthType,
  gatewayConnectNeedsCredentials,
  templateConnectNeedsCredentials,
} from "./gatewayConnect";

function credentials(
  overrides: Partial<GatewayConnectCredentials> = {},
): GatewayConnectCredentials {
  return { ...GATEWAY_CONNECT_DEFAULTS, ...overrides };
}

function fakes() {
  const client: InstallFlowClient = {
    installMcpTemplate: vi.fn().mockResolvedValue({ id: "inst-1" }),
    installCustomMcpServer: vi.fn().mockResolvedValue({ id: "inst-2" }),
    authorizeMcpInstallation: vi
      .fn()
      .mockResolvedValue({ redirect_url: "https://auth" }),
  };
  const oauth: IOAuthCallback = {
    getCallbackUrl: vi
      .fn()
      .mockResolvedValue({ callbackUrl: "posthog://callback" }),
    openAndWaitForCallback: vi.fn().mockResolvedValue({ success: true }),
  };
  return { client, oauth };
}

describe("gatewayConnectAuthType", () => {
  it.each([
    [
      "oauth template",
      { template_id: "t1", template_auth_type: "oauth" },
      "oauth",
    ],
    [
      "api-key template",
      { template_id: "t1", template_auth_type: "api_key" },
      "api_key",
    ],
    [
      "template with no reported type",
      { template_id: "t1", template_auth_type: null },
      "oauth",
    ],
    [
      "custom server — member chooses",
      { template_id: null, template_auth_type: null },
      null,
    ],
  ] as const)("%s", (_label, server, expected) => {
    expect(gatewayConnectAuthType(server)).toBe(expected);
  });
});

describe("gatewayConnectNeedsCredentials", () => {
  it.each([
    [
      "oauth template connects directly",
      { template_id: "t1", template_auth_type: "oauth" },
      false,
    ],
    [
      "api-key template asks for the key",
      { template_id: "t1", template_auth_type: "api_key" },
      true,
    ],
    [
      "custom server asks the member to choose",
      { template_id: null, template_auth_type: null },
      true,
    ],
  ] as const)("%s", (_label, server, expected) => {
    expect(gatewayConnectNeedsCredentials(server)).toBe(expected);
  });
});

describe("templateConnectNeedsCredentials", () => {
  it.each([
    ["oauth template", { auth_type: "oauth" }, false],
    ["api-key template", { auth_type: "api_key" }, true],
    ["auth type unreported", {}, false],
  ] as const)("%s", (_label, template, expected) => {
    expect(
      templateConnectNeedsCredentials(
        template as { auth_type?: "oauth" | "api_key" },
      ),
    ).toBe(expected);
  });
});

describe("canSubmitGatewayConnect", () => {
  it.each([
    ["oauth needs no key", credentials(), true],
    [
      "api_key with a key",
      credentials({ authType: "api_key", apiKey: "sk-1" }),
      true,
    ],
    [
      "api_key with a blank key",
      credentials({ authType: "api_key", apiKey: "  " }),
      false,
    ],
  ])("%s", (_label, input, expected) => {
    expect(canSubmitGatewayConnect(input)).toBe(expected);
  });
});

describe("connectGatewayServer", () => {
  const template = {
    template_id: "t1",
    name: "Linear",
    url: "https://mcp.linear.app",
    description: "",
  };
  const custom = {
    template_id: null,
    name: "Internal Wiki",
    url: "https://mcp.example.com/sse",
    description: "Wiki tools",
  };

  it("installs a template with the member's API key", async () => {
    const { client, oauth } = fakes();
    await connectGatewayServer(
      client,
      oauth,
      template,
      credentials({ authType: "api_key", apiKey: "sk-1" }),
    );
    expect(client.installMcpTemplate).toHaveBeenCalledWith({
      template_id: "t1",
      api_key: "sk-1",
      install_source: "posthog-code",
      posthog_code_callback_url: "posthog://callback",
    });
    expect(client.installCustomMcpServer).not.toHaveBeenCalled();
  });

  it("installs an oauth template without a key by default", async () => {
    const { client, oauth } = fakes();
    await connectGatewayServer(client, oauth, template);
    expect(client.installMcpTemplate).toHaveBeenCalledWith({
      template_id: "t1",
      api_key: undefined,
      install_source: "posthog-code",
      posthog_code_callback_url: "posthog://callback",
    });
  });

  it("connects a custom server with the chosen api_key mechanism", async () => {
    const { client, oauth } = fakes();
    const result = await connectGatewayServer(
      client,
      oauth,
      custom,
      credentials({
        authType: "api_key",
        apiKey: "sk-2",
        // A stale value from flipping the auth select must not leak through.
        clientId: "leftover",
        clientSecret: "leftover",
      }),
    );
    expect(client.installCustomMcpServer).toHaveBeenCalledWith({
      name: "Internal Wiki",
      url: "https://mcp.example.com/sse",
      description: "Wiki tools",
      auth_type: "api_key",
      api_key: "sk-2",
      client_id: undefined,
      client_secret: undefined,
      install_source: "posthog-code",
      posthog_code_callback_url: "posthog://callback",
    });
    // API-key installs return no redirect, so no browser round-trip.
    expect(oauth.openAndWaitForCallback).not.toHaveBeenCalled();
    expect(result).toEqual({ success: true });
  });

  it("connects a custom server over oauth with optional client credentials", async () => {
    const { client, oauth } = fakes();
    vi.mocked(client.installCustomMcpServer).mockResolvedValue({
      redirect_url: "https://auth.example.com",
    });
    await connectGatewayServer(
      client,
      oauth,
      custom,
      credentials({ clientId: " id ", clientSecret: "secret" }),
    );
    expect(client.installCustomMcpServer).toHaveBeenCalledWith(
      expect.objectContaining({
        auth_type: "oauth",
        api_key: undefined,
        client_id: "id",
        client_secret: "secret",
      }),
    );
    expect(oauth.openAndWaitForCallback).toHaveBeenCalledWith({
      redirectUrl: "https://auth.example.com",
    });
  });
});
