import type {
  AgentSideConnection,
  RequestPermissionRequest,
  RequestPermissionResponse,
} from "@agentclientprotocol/sdk";
import type {
  McpServerConnection,
  McpToolApprovalState,
  McpToolPolicy,
} from "@posthog/shared";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  clearMcpToolMetadataCache,
  replaceCloudMcpToolPolicies,
} from "../adapters/claude/mcp/tool-metadata";
import { canUseTool } from "../adapters/claude/permissions/permission-handlers";
import type {
  AppServerClientHandlers,
  AppServerRpc,
} from "../adapters/codex-app-server/app-server-client";
import { CodexAppServerAgent } from "../adapters/codex-app-server/codex-app-server-agent";
import {
  BACKGROUND_MCP_APPROVAL_DENIAL,
  BLOCKED_MCP_TOOL_DENIAL,
} from "../adapters/mcp-tool-policy";
import type { PostHogAPIClient } from "../posthog-api";
import { Logger } from "../utils/logger";
import { AgentServer } from "./agent-server";
import type { JwtPayload } from "./jwt";

type ApprovalPath = "claude" | "codex-command" | "codex-elicitation";

const payload: JwtPayload = {
  mode: "interactive",
  task_id: "task-policy-test",
  run_id: "run-policy-test",
  team_id: 1,
  user_id: 1,
  distinct_id: "test-user",
};
const installation: McpServerConnection = {
  name: "Policy Server",
  type: "http",
  url: "https://posthog.example.com/api/environments/1/mcp_server_installations/test-installation/proxy/",
  headers: [],
};

function policy(approvalState: McpToolApprovalState): McpToolPolicy {
  return {
    serverName: installation.name,
    installationId: "test-installation",
    toolName: "protected_tool",
    approvalState,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

async function createCloud(
  path: ApprovalPath,
  mode: "interactive" | "background",
  policies: McpToolPolicy[],
) {
  const server = new AgentServer({
    port: 0,
    jwtPublicKey: "",
    apiUrl: "https://posthog.example.com",
    apiKey: "test-token",
    projectId: 1,
    mode,
    taskId: payload.task_id,
    runId: payload.run_id,
    runtimeAdapter: path === "claude" ? "claude" : "codex",
    mcpServers: [installation],
  }) as unknown as {
    posthogAPI: PostHogAPIClient;
    session: {
      payload: JwtPayload;
      permissionMode: string;
      hasDesktopConnected: boolean;
      sessionMeta: Record<string, unknown>;
      logWriter: { appendRawLine: ReturnType<typeof vi.fn> };
    };
    pendingPermissions: Map<string, unknown>;
    loadMcpRuntimeConfiguration(): Promise<{
      servers: McpServerConnection[];
      policies: McpToolPolicy[];
    }>;
    createCloudClient(
      payload: JwtPayload,
    ): Pick<AgentSideConnection, "requestPermission">;
    relayPermissionToClient(
      params: RequestPermissionRequest,
    ): Promise<RequestPermissionResponse>;
    resolvePermission(id: string, option: string): string;
    broadcastEvent(event: unknown): void;
  };
  const loaded = vi
    .spyOn(server.posthogAPI, "getMcpRuntimeConfiguration")
    .mockImplementation(async (servers) => ({ servers, policies }));
  const approve = vi
    .spyOn(server.posthogAPI, "approveMcpTool")
    .mockResolvedValue();
  const configuration = await server.loadMcpRuntimeConfiguration();
  const appendRawLine = vi.fn();
  const events = vi.spyOn(server, "broadcastEvent");
  server.session = {
    payload,
    permissionMode: "auto",
    hasDesktopConnected: true,
    sessionMeta: { mcpToolPolicies: configuration.policies },
    logWriter: { appendRawLine },
  };
  return {
    server,
    loaded,
    approve,
    events,
    appendRawLine,
    configuration,
    client: server.createCloudClient({ ...payload, mode }),
  };
}

async function createAdapter(
  path: ApprovalPath,
  cloud: Awaited<ReturnType<typeof createCloud>>,
) {
  const upstream = vi.fn();
  const updates = vi.fn(async () => {});
  const permission = vi.fn(
    (request: RequestPermissionRequest): Promise<RequestPermissionResponse> =>
      cloud.client.requestPermission(request),
  );
  const client = {
    requestPermission: permission,
    sessionUpdate: updates,
    extNotification: vi.fn(),
  } as unknown as AgentSideConnection;
  if (path === "claude") {
    replaceCloudMcpToolPolicies(cloud.configuration.policies);
    return {
      upstream,
      updates,
      permission,
      async invoke() {
        const result = await canUseTool({
          session: {
            cloudMode: true,
            mcpToolPolicies: cloud.configuration.policies,
            permissionMode: "auto",
            cwd: "/tmp",
            settingsManager: { getRepoRoot: () => "/tmp" },
          },
          toolName: "mcp__Policy_Server__protected_tool",
          toolInput: { value: "local test data" },
          toolUseID: "tool-1",
          sessionId: "session-1",
          fileContentCache: {},
          client,
          logger: new Logger({ debug: false }),
          updateConfigOption: vi.fn(),
          applySessionMode: vi.fn(),
        } as unknown as Parameters<typeof canUseTool>[0]);
        if (result.behavior === "allow") upstream();
        return result;
      },
    };
  }
  let handlers!: AppServerClientHandlers;
  const rpc: AppServerRpc = {
    request: vi.fn(async () => ({
      thread: { id: "thread-1" },
    })) as AppServerRpc["request"],
    notify: vi.fn(),
    close: vi.fn(async () => {}),
  };
  const agent = new CodexAppServerAgent(client, {
    processOptions: { binaryPath: "/test/codex" },
    rpcFactory: (callbacks) => {
      handlers = callbacks;
      return rpc;
    },
  });
  await agent.initialize({ protocolVersion: 1, clientCapabilities: {} });
  await agent.newSession({
    cwd: "/tmp",
    mcpServers: cloud.configuration.servers,
    _meta: {
      environment: "cloud",
      permissionMode: "auto",
      mcpToolPolicies: cloud.configuration.policies,
    },
  });
  return {
    upstream,
    updates,
    permission,
    async invoke() {
      handlers.onNotification?.("item/started", {
        item: {
          type: "mcpToolCall",
          id: "tool-1",
          server: "Policy_Server",
          tool: "protected_tool",
          arguments: {},
        },
      });
      const response = (await handlers.onRequest?.(
        path === "codex-command"
          ? "item/commandExecution/requestApproval"
          : "mcpServer/elicitation/request",
        {
          itemId: "tool-1",
          serverName: "Policy_Server",
          message: "Approve protected tool",
          availableDecisions: ["accept", "acceptForSession", "decline"],
        },
      )) as { decision?: string; action?: string };
      if (response.decision === "accept" || response.action === "accept")
        upstream();
      return response;
    },
  };
}

describe.each<ApprovalPath>(["claude", "codex-command", "codex-elicitation"])(
  "cloud MCP policy through %s",
  (path) => {
    afterEach(() => {
      clearMcpToolMetadataCache();
      vi.restoreAllMocks();
    });

    it.each([
      ["interactive", "approved", true],
      ["background", "approved", true],
      ["background", "needs_approval", false],
      ["interactive", "do_not_use", false],
      ["background", "do_not_use", false],
    ] as const)("%s %s executes: %s", async (mode, state, executes) => {
      const cloud = await createCloud(path, mode, [policy(state)]);
      const adapter = await createAdapter(path, cloud);
      const result = await adapter.invoke();
      expect(adapter.upstream).toHaveBeenCalledTimes(executes ? 1 : 0);
      expect(cloud.server.pendingPermissions.size).toBe(0);
      expect(cloud.approve).not.toHaveBeenCalled();
      if (!executes) {
        const reason =
          state === "needs_approval"
            ? BACKGROUND_MCP_APPROVAL_DENIAL
            : BLOCKED_MCP_TOOL_DENIAL;
        expect(JSON.stringify(adapter.updates.mock.calls)).toContain(reason);
        expect(result).toMatchObject(
          path === "claude"
            ? { behavior: "deny", message: reason, interrupt: false }
            : path === "codex-command"
              ? { decision: "decline" }
              : { action: "decline" },
        );
      }
    });

    it.each(["allow", "reject", "persistence failure"] as const)(
      "holds foreground execution until %s, including a disconnect",
      async (decision) => {
        const cloud = await createCloud(path, "interactive", [
          policy("needs_approval"),
        ]);
        const persistence = deferred<void>();
        cloud.approve.mockReturnValue(persistence.promise);
        const adapter = await createAdapter(path, cloud);
        const result = adapter.invoke();
        await vi.waitFor(() =>
          expect(cloud.server.pendingPermissions.size).toBe(1),
        );
        expect(adapter.upstream).not.toHaveBeenCalled();
        const requestId = [...cloud.server.pendingPermissions.keys()][0];
        const request = cloud.events.mock.calls.find(
          ([event]) =>
            (event as { type?: string }).type === "permission_request",
        )?.[0];
        expect(request).toMatchObject({
          options: [
            {
              optionId: "allow_always",
              name: "Always allow",
              _meta: { preservePermissionMode: true },
            },
            { optionId: "reject", name: "Reject" },
          ],
          toolCall: {
            _meta: {
              posthog: {
                approvalReason: "mcp_tool_policy",
                mcpInstallationId: "test-installation",
              },
            },
          },
        });
        expect(
          cloud.appendRawLine.mock.calls.some(
            ([, line]) => JSON.parse(line).params.requestId === requestId,
          ),
        ).toBe(true);

        cloud.server.session.hasDesktopConnected = false;
        expect(cloud.server.pendingPermissions.has(requestId)).toBe(true);
        cloud.server.session.hasDesktopConnected = true;
        expect(
          cloud.server.resolvePermission(
            requestId,
            decision === "reject" ? "reject" : "allow_always",
          ),
        ).toBe("resolved");
        if (decision !== "reject") {
          await vi.waitFor(() =>
            expect(cloud.approve).toHaveBeenCalledWith(
              "test-installation",
              "protected_tool",
              installation,
            ),
          );
          expect(adapter.upstream).not.toHaveBeenCalled();
          if (decision === "persistence failure")
            persistence.reject(new Error("test persistence failure"));
          else persistence.resolve();
        }
        const response = await result;
        expect(adapter.upstream).toHaveBeenCalledTimes(
          decision === "allow" ? 1 : 0,
        );
        expect(response).not.toHaveProperty("updatedPermissions");
        expect(response).not.toEqual({ decision: "acceptForSession" });
        expect(cloud.server.pendingPermissions.size).toBe(0);
        if (decision === "allow") {
          await adapter.invoke();
          expect(adapter.upstream).toHaveBeenCalledTimes(2);
          expect(cloud.approve).toHaveBeenCalledOnce();
        }
      },
    );

    it("denies an approval whose policy changed while persistence was pending", async () => {
      const cloud = await createCloud(path, "interactive", [
        policy("needs_approval"),
      ]);
      const persistence = deferred<void>();
      cloud.approve.mockReturnValue(persistence.promise);
      const adapter = await createAdapter(path, cloud);
      const result = adapter.invoke();
      await vi.waitFor(() =>
        expect(cloud.server.pendingPermissions.size).toBe(1),
      );
      cloud.server.resolvePermission(
        [...cloud.server.pendingPermissions.keys()][0],
        "allow_always",
      );
      await vi.waitFor(() => expect(cloud.approve).toHaveBeenCalledOnce());
      cloud.loaded.mockResolvedValueOnce({
        servers: [installation],
        policies: [policy("do_not_use")],
      });
      await cloud.server.loadMcpRuntimeConfiguration();
      persistence.resolve();
      await result;
      expect(adapter.upstream).not.toHaveBeenCalled();
    });

    it("preserves cancellation without producing rejection feedback", async () => {
      const cloud = await createCloud(path, "interactive", [
        policy("needs_approval"),
      ]);
      vi.spyOn(cloud.server, "relayPermissionToClient").mockResolvedValue({
        outcome: { outcome: "cancelled" },
      });
      const adapter = await createAdapter(path, cloud);
      const result = adapter.invoke();
      if (path === "claude") {
        await expect(result).rejects.toThrow("Tool use aborted");
      } else {
        await expect(result).resolves.toMatchObject(
          path === "codex-command"
            ? { decision: "cancel" }
            : { action: "cancel" },
        );
      }
      expect(adapter.upstream).not.toHaveBeenCalled();
      expect(cloud.approve).not.toHaveBeenCalled();
      expect(JSON.stringify(adapter.updates.mock.calls)).not.toContain(
        "The user rejected",
      );
    });

    it("excludes a failed installation and recovers with fresh policies and actor credentials", async () => {
      const cloud = await createCloud(path, "interactive", [
        policy("needs_approval"),
      ]);
      const adapter = await createAdapter(path, cloud);
      cloud.loaded.mockResolvedValueOnce({ servers: [], policies: [] });
      expect(await cloud.server.loadMcpRuntimeConfiguration()).toEqual({
        servers: [],
        policies: [],
      });
      await adapter.invoke();
      expect(adapter.upstream).not.toHaveBeenCalled();
      expect(cloud.server.pendingPermissions.size).toBe(0);
      expect(cloud.events).toHaveBeenCalledWith(
        expect.objectContaining({
          type: "error",
          message: expect.stringContaining(
            "Could not load tool approval policies",
          ),
        }),
      );
      const refreshedInstallation = {
        ...installation,
        headers: [{ name: "Authorization", value: "Bearer new-actor-token" }],
      };
      cloud.loaded.mockResolvedValueOnce({
        servers: [refreshedInstallation],
        policies: [policy("needs_approval")],
      });
      await cloud.server.loadMcpRuntimeConfiguration();
      const recovered = adapter.invoke();
      await vi.waitFor(() =>
        expect(cloud.server.pendingPermissions.size).toBe(1),
      );
      expect(adapter.upstream).not.toHaveBeenCalled();
      cloud.server.resolvePermission(
        [...cloud.server.pendingPermissions.keys()][0],
        "allow_always",
      );
      await recovered;
      expect(cloud.approve).toHaveBeenCalledWith(
        "test-installation",
        "protected_tool",
        refreshedInstallation,
      );
      expect(adapter.upstream).toHaveBeenCalledOnce();
    });
  },
);
