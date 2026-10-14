import type { PiRpcClient } from "@posthog/agent/pi/rpc-client";
import { getLlmGatewayUrl } from "@posthog/agent/posthog-api";
import type { RootLogger } from "@posthog/di/logger";
import { ROOT_LOGGER } from "@posthog/di/logger";
import { getCloudUrlFromRegion } from "@posthog/shared";
import {
  AGENT_AUTH,
  AGENT_MCP_APPS,
  MCP_SERVER_CONNECTION_SOURCE,
} from "@posthog/workspace-server/services/agent/identifiers";
import type {
  AgentAuth,
  AgentMcpApps,
} from "@posthog/workspace-server/services/agent/ports";
import type { AuthProxyService } from "@posthog/workspace-server/services/auth-proxy/auth-proxy";
import { AUTH_PROXY_SERVICE } from "@posthog/workspace-server/services/auth-proxy/identifiers";
import { Container } from "inversify";
import { describe, expect, it, vi } from "vitest";
import { DesktopPiRpcClientFactory } from "./desktop-pi-rpc-client-factory";

const createPiRpcClient = vi.hoisted(() => vi.fn());
const createLocalRuntimeMcpServers = vi.hoisted(() =>
  vi.fn(() => ({
    "posthog-code-tools": {
      args: ["local-tools-mcp-server.js"],
      command: process.execPath,
      directTools: true,
      env: { POSTHOG_LOCAL_TOOLS_ENABLED: "show_actions" },
      lifecycle: "eager",
      requestTimeoutMs: 300_000,
      transport: "stdio",
    },
  })),
);
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
  createLocalRuntimeMcpServers,
  createPiRpcClient,
  createRuntimeMcpServers,
}));

describe("DesktopPiRpcClientFactory", () => {
  it("routes Dev Cloud Pi sessions through the hosted development gateway", async () => {
    const auth = {
      getOAuthCredentials: vi.fn(async () => ({
        access: "access-token",
        refresh: "refresh-token",
        expires: 1,
        region: "dev-cloud" as const,
      })),
      getState: vi.fn(() => ({ currentProjectId: 1 })),
      getValidAccessToken: vi.fn(async () => ({
        accessToken: "access-token",
        apiHost: "https://app.dev.posthog.dev",
      })),
    } as unknown as AgentAuth;
    const authProxy = {
      start: vi.fn(async (url: string) =>
        url === "https://app.dev.posthog.dev"
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
    const mcpApps = {
      addServerConfigs: vi.fn(),
      handleDiscovery: vi.fn(async () => {}),
    };
    const factory = new DesktopPiRpcClientFactory(
      auth,
      authProxy,
      mcpServerSource,
      mcpApps as unknown as AgentMcpApps,
      rootLogger,
      {
        getRoute: vi.fn(async () => ({ mode: "legacy" as const, reason: "x" })),
        remint: vi.fn(),
        fallBack: vi.fn(),
      },
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
      }),
    ).resolves.toBe(client);
    expect(authProxy.start).toHaveBeenCalledWith(
      getLlmGatewayUrl(getCloudUrlFromRegion("dev-cloud")),
      {
        "x-posthog-property-task_id": "task-1",
        "x-posthog-property-$ai_session_id": "task-1",
        "X-PostHog-Project-Id": "1",
      },
    );
    expect(authProxy.start).toHaveBeenCalledWith("https://app.dev.posthog.dev");
    expect(createLocalRuntimeMcpServers).toHaveBeenCalledWith("/workspace");
    expect(mcpApps.addServerConfigs).toHaveBeenCalledWith([
      {
        name: "posthog",
        url: "http://127.0.0.1:4321/posthog",
        headers: { "x-posthog-project-id": "1" },
      },
    ]);
    expect(mcpApps.handleDiscovery).toHaveBeenCalledWith(["posthog"]);
    expect(createPiRpcClient).toHaveBeenCalledWith({
      enrichment: {
        apiUrl: "http://127.0.0.1:5678",
        publicApiUrl: "https://app.dev.posthog.dev",
        projectId: 1,
        apiKey: "posthog-code-auth-proxy",
      },
      mcpToolPolicies: policies,
      runtimeMcpServers: {
        "posthog-code-tools": {
          args: ["local-tools-mcp-server.js"],
          command: process.execPath,
          directTools: true,
          env: { POSTHOG_LOCAL_TOOLS_ENABLED: "show_actions" },
          lifecycle: "eager",
          requestTimeoutMs: 300_000,
          transport: "stdio",
        },
        posthog: {
          args: [],
          directTools: false,
          headers: { "x-posthog-project-id": "1" },
          lifecycle: "lazy",
          transport: "streamable-http",
          url: "http://127.0.0.1:4321/posthog",
        },
      },
      taskContext: {
        projectId: 1,
        apiHost: "https://app.dev.posthog.dev",
        taskId: "task-1",
        cwd: "/workspace",
        environment: "local",
        customInstructions: "Keep the patch small.",
        additionalDirectories: ["/tmp/shared"],
        channelMode: true,
      },
      providerOptions: {
        region: "dev-cloud",
        baseUrl: "http://127.0.0.1:1234",
        apiKey: "posthog-code-auth-proxy",
      },
      extensions: ["context-wiki"],
    });
  });

  it.each([
    ["go", "http://127.0.0.1:1234/session"],
    ["legacy", "http://127.0.0.1:1234/legacy"],
  ] as const)(
    "routes a Pi session to the %s gateway by the source's route",
    async (mode, expectedBaseUrl) => {
      const auth = {
        getOAuthCredentials: vi.fn(async () => ({
          access: "access-token",
          refresh: null,
          expires: 1,
          region: "us" as const,
        })),
        getState: vi.fn(() => ({ currentProjectId: 7 })),
        getValidAccessToken: vi.fn(async () => ({
          accessToken: "access-token",
          apiHost: "https://us.posthog.com",
        })),
      } as unknown as AgentAuth;
      const authProxy = {
        start: vi.fn(async (url: string) =>
          url === "https://us.posthog.com"
            ? "http://127.0.0.1:5678"
            : "http://127.0.0.1:1234/legacy",
        ),
        startGatewaySession: vi.fn(async () => "http://127.0.0.1:1234/session"),
      } as unknown as AuthProxyService;
      const source = {
        getRoute: vi.fn(async () =>
          mode === "go"
            ? { mode: "go", token: "phe_x", teamId: 7, projectId: 7 }
            : { mode: "legacy", reason: "not_rolled_out" },
        ),
        remint: vi.fn(),
        fallBack: vi.fn(),
      };
      createPiRpcClient.mockReturnValue({} as PiRpcClient);
      const factory = new DesktopPiRpcClientFactory(
        auth,
        authProxy,
        {
          getMcpRuntimeConfiguration: vi.fn(async () => ({
            servers: [],
            policies: [],
          })),
        },
        {
          addServerConfigs: vi.fn(),
          handleDiscovery: vi.fn(async () => {}),
        } as unknown as AgentMcpApps,
        {
          scope: () => ({
            debug: vi.fn(),
            info: vi.fn(),
            warn: vi.fn(),
            error: vi.fn(),
          }),
        } as unknown as RootLogger,
        source as never,
      );

      await factory.create({ taskContext: { taskId: "task-9", cwd: "/w" } });

      expect(source.getRoute).toHaveBeenCalledWith(7, { awaitRecheck: true });
      expect(createPiRpcClient).toHaveBeenLastCalledWith(
        expect.objectContaining({
          providerOptions: {
            region: "us",
            baseUrl: expectedBaseUrl,
            apiKey: "posthog-code-auth-proxy",
          },
        }),
      );
      if (mode === "go") {
        expect(authProxy.startGatewaySession).toHaveBeenCalledWith({
          projectId: 7,
          legacyGatewayUrl: getLlmGatewayUrl("https://us.posthog.com"),
          headers: {
            "x-posthog-property-task_id": "task-9",
            "x-posthog-property-$ai_session_id": "task-9",
            "X-PostHog-Project-Id": "7",
          },
        });
      }
    },
  );
});

it("refuses to resolve the Pi factory without a gateway credential source", () => {
  const container = new Container();
  for (const token of [
    AGENT_AUTH,
    AUTH_PROXY_SERVICE,
    MCP_SERVER_CONNECTION_SOURCE,
    AGENT_MCP_APPS,
    ROOT_LOGGER,
  ]) {
    container.bind(token).toConstantValue({});
  }
  container.bind(DesktopPiRpcClientFactory).toSelf();

  expect(() => container.get(DesktopPiRpcClientFactory)).toThrow();
});
