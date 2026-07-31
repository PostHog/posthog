import type { PiRpcClient } from "@posthog/agent/pi/rpc-client";
import { getLlmGatewayUrl } from "@posthog/agent/posthog-api";
import { getCloudUrlFromRegion } from "@posthog/shared";
import type { AgentAuth } from "@posthog/workspace-server/services/agent/ports";
import type { AuthProxyService } from "@posthog/workspace-server/services/auth-proxy/auth-proxy";
import { describe, expect, it, vi } from "vitest";
import { DesktopPiRpcClientFactory } from "./desktop-pi-rpc-client-factory";

const createPiRpcClient = vi.hoisted(() => vi.fn());
const createRuntimeMcpServers = vi.hoisted(() =>
  vi.fn(() => ({
    posthog: {
      args: [],
      directTools: false,
      headers: { "x-posthog-project-id": "1" },
      lifecycle: "lazy",
      transport: "streamable-http",
      url: "http://127.0.0.1:4321/posthog",
    },
  })),
);

vi.mock("@posthog/agent/pi/rpc-client", () => ({
  createPiRpcClient,
  createRuntimeMcpServers,
}));

describe("DesktopPiRpcClientFactory", () => {
  it("routes Pi through the shared host auth proxy", async () => {
    const auth = {
      getOAuthCredentials: vi.fn(async () => ({
        access: "access-token",
        refresh: "refresh-token",
        expires: 1,
        region: "eu" as const,
      })),
    } as unknown as AgentAuth;
    const authProxy = {
      start: vi.fn(async () => "http://127.0.0.1:1234"),
    } as unknown as AuthProxyService;
    const mcpServerSource = {
      getMcpServerConnections: vi.fn(async () => [
        {
          name: "posthog",
          type: "http" as const,
          url: "http://127.0.0.1:4321/posthog",
          headers: [{ name: "x-posthog-project-id", value: "1" }],
        },
      ]),
    };
    const client = {} as PiRpcClient;
    createPiRpcClient.mockReturnValue(client);
    const factory = new DesktopPiRpcClientFactory(
      auth,
      authProxy,
      mcpServerSource,
    );

    await expect(factory.create({ cwd: "/workspace" })).resolves.toBe(client);
    expect(authProxy.start).toHaveBeenCalledWith(
      getLlmGatewayUrl(getCloudUrlFromRegion("eu")),
    );
    expect(createPiRpcClient).toHaveBeenCalledWith({
      cwd: "/workspace",
      runtimeMcpServers: {
        posthog: {
          args: [],
          directTools: false,
          headers: { "x-posthog-project-id": "1" },
          lifecycle: "lazy",
          transport: "streamable-http",
          url: "http://127.0.0.1:4321/posthog",
        },
      },
      providerOptions: {
        region: "eu",
        baseUrl: "http://127.0.0.1:1234",
        apiKey: "posthog-code-auth-proxy",
      },
    });
  });
});
