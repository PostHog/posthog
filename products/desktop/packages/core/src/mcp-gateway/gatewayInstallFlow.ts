import type { McpServerInstallation } from "@posthog/api-client/types";
import type {
  IOAuthCallback,
  OAuthCallbackResult,
} from "../mcp-servers/installFlow";
import type { GatewayInstallRequest } from "./gatewayAddServer";

interface OAuthRedirect {
  redirect_url: string;
}

interface GatewayInstallClient {
  installCustomMcpServer(
    options: GatewayInstallRequest & {
      install_source?: "posthog" | "posthog-code";
      posthog_code_callback_url?: string;
    },
  ): Promise<McpServerInstallation | OAuthRedirect>;
}

/**
 * Register a custom server with the gateway. OAuth servers round-trip through
 * the host browser callback; API-key servers complete immediately.
 */
export async function registerGatewayServerWithOAuth(
  client: GatewayInstallClient,
  oauth: IOAuthCallback,
  request: GatewayInstallRequest,
): Promise<OAuthCallbackResult> {
  const { callbackUrl } = await oauth.getCallbackUrl();
  const data = await client.installCustomMcpServer({
    ...request,
    install_source: "posthog-code",
    posthog_code_callback_url: callbackUrl,
  });
  if ("redirect_url" in data && data.redirect_url) {
    return oauth.openAndWaitForCallback({ redirectUrl: data.redirect_url });
  }
  return { success: true };
}
