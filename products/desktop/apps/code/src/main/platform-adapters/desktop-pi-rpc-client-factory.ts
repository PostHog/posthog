import {
  createPiRpcClient,
  createRuntimeMcpServers,
  type PiRpcClient,
} from "@posthog/agent/pi/rpc-client";
import { getLlmGatewayUrl } from "@posthog/agent/posthog-api";
import { type CloudRegion, getCloudUrlFromRegion } from "@posthog/shared";
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
  private proxyRegion?: CloudRegion;
  private proxyUrlPromise?: Promise<string>;

  constructor(
    @inject(AGENT_AUTH) private readonly auth: AgentAuth,
    @inject(AUTH_PROXY_SERVICE)
    private readonly authProxy: AuthProxyService,
    @inject(MCP_SERVER_CONNECTION_SOURCE)
    private readonly mcpServerSource: McpServerConnectionSource,
  ) {}

  async create(input: {
    taskId: string;
    cwd: string;
    model?: string;
    sessionFile?: string;
  }): Promise<PiRpcClient> {
    const credentials = await this.auth.getOAuthCredentials();
    if (!credentials) {
      throw new Error("Pi requires PostHog authentication");
    }

    const baseUrl = await this.getProxyUrl(credentials.region);

    const mcpConfiguration =
      await this.mcpServerSource.getMcpRuntimeConfiguration();
    const runtimeMcpServers = createRuntimeMcpServers(mcpConfiguration.servers);

    return createPiRpcClient({
      cwd: input.cwd,
      model: input.model,
      sessionFile: input.sessionFile,
      runtimeMcpServers,
      mcpToolPolicies: mcpConfiguration.policies,
      providerOptions: {
        region: credentials.region,
        baseUrl,
        apiKey: PROXY_API_KEY,
      },
    });
  }

  private getProxyUrl(region: CloudRegion): Promise<string> {
    if (this.proxyRegion !== region || !this.proxyUrlPromise) {
      this.proxyRegion = region;
      const gatewayUrl = getLlmGatewayUrl(getCloudUrlFromRegion(region));
      this.proxyUrlPromise = this.authProxy.start(gatewayUrl);
    }

    return this.proxyUrlPromise;
  }
}
