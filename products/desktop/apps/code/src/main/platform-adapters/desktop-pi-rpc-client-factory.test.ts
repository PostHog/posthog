import type { PiRpcClient } from "@posthog/agent/pi/rpc-client";
import { getLlmGatewayUrl } from "@posthog/agent/posthog-api";
import type { RootLogger } from "@posthog/di/logger";
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
      getState: vi.fn(() => ({ currentProjectId: 1 })),
      getValidAccessToken: vi.fn(async () => ({
        accessToken: "access-token",
        apiHost: "https://eu.posthog.com",
      })),
    } as unknown as AgentAuth;
    const authProxy = {
      start: vi.fn(async (url: string) =>
        url === "https://eu.posthog.com"
          ? "http://127.0.0.1:5678"
          : "http://127.0.0.1:1234",
      ),
    } as unknown as AuthProxyService;
    const policies = [
      {
        serverName: "Cloudflare",
        toolName: "search",
        installationId: "installation-1",
        approvalState: "needs_approval" as const,
      },
    ];
    const mcpServerSource = {
      getMcpRuntimeConfiguration: vi.fn(async () => ({
        servers: [
          {
            name: "posthog",
            type: "http" as const,
            url: "http://127.0.0.1:4321/posthog",
            headers: [{ name: "x-posthog-project-id", value: "1" }],
          },
        ],
        policies,
      })),
    };
    const client = {} as PiRpcClient;
    createPiRpcClient.mockReturnValue(client);
    const rootLogger = {
      scope: () => ({
        debug: vi.fn(),
        info: vi.fn(),
        warn: vi.fn(),
        error: vi.fn(),
      }),
    } as unknown as RootLogger;
    const factory = new DesktopPiRpcClientFactory(
      auth,
      authProxy,
      mcpServerSource,
      rootLogger,
    );

    await expect(
      factory.create({
        taskContext: {
          taskId: "task-1",
          cwd: "/workspace",
          customInstructions: "Keep the patch small.",
          additionalDirectories: ["/tmp/shared"],
          channelMode: true,
        },
        projectTrusted: true,
      }),
    ).resolves.toBe(client);
    expect(authProxy.start).toHaveBeenCalledWith(
      getLlmGatewayUrl(getCloudUrlFromRegion("eu")),
      {
        "x-posthog-property-task_id": "task-1",
        "x-posthog-property-$ai_session_id": "task-1",
        "X-PostHog-Project-Id": "1",
      },
    );
    expect(authProxy.start).toHaveBeenCalledWith("https://eu.posthog.com");
    expect(createPiRpcClient).toHaveBeenCalledWith({
      enrichment: {
        apiUrl: "http://127.0.0.1:5678",
        publicApiUrl: "https://eu.posthog.com",
        projectId: 1,
        apiKey: "posthog-code-auth-proxy",
      },
      mcpToolPolicies: policies,
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
      projectTrusted: true,
      taskContext: {
        projectId: 1,
        apiHost: "https://eu.posthog.com",
        taskId: "task-1",
        cwd: "/workspace",
        environment: "local",
        customInstructions: "Keep the patch small.",
        additionalDirectories: ["/tmp/shared"],
        channelMode: true,
      },
      providerOptions: {
        region: "eu",
        baseUrl: "http://127.0.0.1:1234",
        apiKey: "posthog-code-auth-proxy",
      },
      extensions: ["context-wiki"],
    });
  });
});
