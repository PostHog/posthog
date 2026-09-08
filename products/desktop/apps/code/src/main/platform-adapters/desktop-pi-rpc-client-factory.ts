import { homedir } from "node:os";
import { join } from "node:path";
import {
  createLocalRuntimeMcpServers,
  createPiRpcClient,
  createRuntimeMcpServers,
  type PiRpcClient,
} from "@posthog/agent/pi/rpc-client";
import type { TaskContext } from "@posthog/agent/pi/task-system-prompt";
import { getLlmGatewayUrl } from "@posthog/agent/posthog-api";
import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import {
  type CloudRegion,
  getCloudUrlFromRegion,
  type McpServerConnection,
} from "@posthog/shared";
import { buildPosthogScopedPropertyHeaderRecord } from "@posthog/shared/posthog-property-headers";
import { prepareContextWiki } from "@posthog/workspace-server/services/agent/context-wiki";
import {
  AGENT_AUTH,
  AGENT_MCP_APPS,
  MCP_SERVER_CONNECTION_SOURCE,
} from "@posthog/workspace-server/services/agent/identifiers";
import type {
  AgentAuth,
  AgentMcpApps,
  McpServerConnectionSource,
} from "@posthog/workspace-server/services/agent/ports";
import type { AuthProxyService } from "@posthog/workspace-server/services/auth-proxy/auth-proxy";
import { AUTH_PROXY_SERVICE } from "@posthog/workspace-server/services/auth-proxy/identifiers";
import type { PiRpcClientFactory } from "@posthog/workspace-server/services/pi-session/identifiers";
import { inject, injectable } from "inversify";

const PROXY_API_KEY = "posthog-code-auth-proxy";

@injectable()
export class DesktopPiRpcClientFactory implements PiRpcClientFactory {
  constructor(
    @inject(AGENT_AUTH) private readonly auth: AgentAuth,
    @inject(AUTH_PROXY_SERVICE)
    private readonly authProxy: AuthProxyService,
    @inject(MCP_SERVER_CONNECTION_SOURCE)
    private readonly mcpServerSource: McpServerConnectionSource,
    @inject(AGENT_MCP_APPS) private readonly mcpApps: AgentMcpApps,
    @inject(ROOT_LOGGER) private readonly rootLogger: RootLogger,
  ) {}

  async create(
    input: Parameters<PiRpcClientFactory["create"]>[0],
  ): Promise<PiRpcClient> {
    const credentials = await this.auth.getOAuthCredentials();
    if (!credentials) {
      throw new Error("Pi requires PostHog authentication");
    }

    const projectId = this.auth.getState().currentProjectId;
    if (!projectId) {
      throw new Error("Pi requires a selected PostHog project");
    }
    const access = await this.auth.getValidAccessToken();
    // Four independent round-trips: proxy URL, auth proxy, MCP config, wiki mount.
    const [baseUrl, enrichmentApiUrl, mcpConfiguration, contextWikiPath] =
      await Promise.all([
        this.getProxyUrl(
          credentials.region,
          projectId,
          input.taskContext.taskId,
        ),
        this.authProxy.start(access.apiHost),
        this.mcpServerSource.getMcpRuntimeConfiguration(),
        this.mountContextWiki(projectId),
      ]);
    const runtimeMcpServers = {
      ...createRuntimeMcpServers(mcpConfiguration.servers),
      ...createLocalRuntimeMcpServers(input.taskContext.cwd),
    };
    this.registerMcpAppsServers(mcpConfiguration.servers);
    const taskContext: TaskContext = {
      projectId,
      apiHost: access.apiHost,
      environment: "local",
      ...input.taskContext,
    };

    return createPiRpcClient({
      model: input.model,
      sessionFile: input.sessionFile,
      taskContext,
      enrichment: {
        apiUrl: enrichmentApiUrl,
        publicApiUrl: access.apiHost,
        projectId,
        apiKey: PROXY_API_KEY,
      },
      runtimeMcpServers,
      mcpToolPolicies: mcpConfiguration.policies,
      providerOptions: {
        region: credentials.region,
        baseUrl,
        apiKey: PROXY_API_KEY,
      },
      extensions: ["context-wiki"],
      contextWikiPath,
    });
  }

  /**
   * Pi sessions don't go through AgentService, so nothing registers the MCP
   * server configs with the MCP Apps service. A tool result that carries a
   * UI resource then fails with "No server config for: posthog" and the
   * interactive view never renders. Register the same server list the
   * session connects to, then run discovery so the exec tool definition and
   * tool-to-UI associations resolve. Best-effort: failures log and the
   * session still starts, with tool results rendered as text.
   *
   * Discovery is fire-and-forget on purpose; there is no race with the first
   * UI-resource result. `discoverServer` publishes its promise in
   * `pendingDiscoveries` synchronously, so a resource fetch that arrives
   * mid-discovery joins that in-flight promise (`ensureServerDiscovered`)
   * and reads the association once it lands. The configs are registered
   * synchronously before discovery starts, so the "No server config" error
   * cannot occur on this path.
   */
  private registerMcpAppsServers(servers: McpServerConnection[]): void {
    this.mcpApps.addServerConfigs(
      servers.map((server) => ({
        name: server.name,
        url: server.url,
        headers: Object.fromEntries(
          (server.headers ?? []).map((header) => [header.name, header.value]),
        ),
      })),
    );
    this.mcpApps
      .handleDiscovery(servers.map((server) => server.name))
      .catch((err) => {
        this.rootLogger
          .scope("pi-mcp-apps")
          .warn("MCP Apps discovery failed for a Pi session", {
            error: err instanceof Error ? err.message : String(err),
          });
      });
  }

  /**
   * Pi sessions don't go through AgentService, so they mount the org's
   * context wiki themselves. Best-effort: the session starts without a wiki
   * on any failure.
   */
  private async mountContextWiki(
    projectId: number,
  ): Promise<string | undefined> {
    try {
      const { apiHost } = await this.auth.getValidAccessToken();
      const mount = await prepareContextWiki({
        apiHost,
        projectId,
        authenticatedFetch: (input, init) =>
          this.auth.authenticatedFetch(fetch, input, init),
        cacheDir: join(homedir(), ".posthog-code", "context-wiki"),
        log: this.rootLogger.scope("pi-context-wiki"),
      });
      return mount?.path;
    } catch (err) {
      this.rootLogger
        .scope("pi-context-wiki")
        .warn("Failed to mount the context wiki", {
          error: err instanceof Error ? err.message : String(err),
        });
      return undefined;
    }
  }

  private getProxyUrl(
    region: CloudRegion,
    projectId: number,
    taskId: string,
  ): Promise<string> {
    const gatewayUrl = getLlmGatewayUrl(getCloudUrlFromRegion(region));
    return this.authProxy.start(
      gatewayUrl,
      buildPosthogScopedPropertyHeaderRecord(
        { task_id: taskId, $ai_session_id: taskId },
        projectId,
      ),
    );
  }
}
