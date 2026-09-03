import { homedir } from "node:os";
import { join } from "node:path";
import {
  createPiRpcClient,
  createRuntimeMcpServers,
  type PiRpcClient,
} from "@posthog/agent/pi/rpc-client";
import { piSubscriptionLoginState } from "@posthog/agent/pi/subscription-login-client";
import type { TaskContext } from "@posthog/agent/pi/task-system-prompt";
import { getLlmGatewayUrl } from "@posthog/agent/posthog-api";
import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import {
  type CloudRegion,
  getCloudUrlFromRegion,
  PI_SUBSCRIPTION_DEFAULT_MODEL_ID,
  type PiSubscriptionProvider,
} from "@posthog/shared";
import { buildPosthogScopedPropertyHeaderRecord } from "@posthog/shared/posthog-property-headers";
import { prepareContextWiki } from "@posthog/workspace-server/services/agent/context-wiki";
import {
  AGENT_AUTH,
  MCP_SERVER_CONNECTION_SOURCE,
} from "@posthog/workspace-server/services/agent/identifiers";
import type {
  AgentAuth,
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
    const runtimeMcpServers = createRuntimeMcpServers(mcpConfiguration.servers);
    const taskContext: TaskContext = {
      projectId,
      apiHost: access.apiHost,
      environment: "local",
      ...input.taskContext,
    };

    const subscription = await this.resolveSubscriptionProvider(
      input.piSubscriptionProvider,
    );

    return createPiRpcClient({
      model: subscription
        ? PI_SUBSCRIPTION_DEFAULT_MODEL_ID[subscription]
        : input.model,
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
      providerOptions: subscription
        ? { provider: subscription }
        : {
            region: credentials.region,
            baseUrl,
            apiKey: PROXY_API_KEY,
          },
      extensions: ["context-wiki"],
      contextWikiPath,
    });
  }

  /**
   * Own-subscription requires an actual stored login: a stale toggle (the
   * user signed out elsewhere, or never finished login) falls back to the
   * PostHog gateway rather than starting a session that can't authenticate,
   * mirroring the same safety net the Claude/Codex ACP adapters use.
   */
  private async resolveSubscriptionProvider(
    requested: PiSubscriptionProvider | undefined,
  ): Promise<PiSubscriptionProvider | undefined> {
    if (!requested) {
      return undefined;
    }
    const loginState = await piSubscriptionLoginState(requested);
    if (loginState !== "logged-in") {
      this.rootLogger
        .scope("pi-rpc-client-factory")
        .warn("Pi own-subscription requested but login is not active", {
          provider: requested,
        });
      return undefined;
    }
    return requested;
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
