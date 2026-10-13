import type {
  McpAgentGrantScope,
  McpAuthType,
  McpGatewayInstallSharingOptions,
} from "@posthog/api-client/posthog-client";
import { isValidMcpUrl } from "../mcp-servers/customServerForm";

export interface GatewayAddServerValues {
  name: string;
  url: string;
  description: string;
  authType: McpAuthType;
  apiKey: string;
  clientId: string;
  clientSecret: string;
  /** Team sharing options are admin-only; agentScope follows the team setting. */
  teamEnabled: boolean;
  agentScope: McpAgentGrantScope;
}

export const GATEWAY_ADD_SERVER_DEFAULTS: GatewayAddServerValues = {
  name: "",
  url: "",
  description: "",
  authType: "oauth",
  apiKey: "",
  clientId: "",
  clientSecret: "",
  teamEnabled: true,
  agentScope: "personal",
};

export function canSubmitGatewayServer(
  values: Pick<GatewayAddServerValues, "name" | "url">,
): boolean {
  return values.name.trim() !== "" && isValidMcpUrl(values.url);
}

export interface GatewayInstallRequest extends McpGatewayInstallSharingOptions {
  name: string;
  url: string;
  description: string;
  auth_type: McpAuthType;
  api_key?: string;
  client_id?: string;
  client_secret?: string;
}

/**
 * install_custom payload for registering a server with the gateway. The
 * credential is always personal to the installer. Team-wide options are
 * attached only for admins; the agent grant scope is attached whenever the
 * team allows this member to manage agent access.
 */
export function buildGatewayInstallRequest(
  values: GatewayAddServerValues,
  options: { isAdmin: boolean; canManageAgentAccess: boolean },
): GatewayInstallRequest {
  return {
    name: values.name.trim(),
    url: values.url.trim(),
    description: values.description.trim(),
    auth_type: values.authType,
    ...(values.authType === "api_key" && values.apiKey
      ? { api_key: values.apiKey }
      : {}),
    ...(values.authType === "oauth" && values.clientId.trim()
      ? { client_id: values.clientId.trim() }
      : {}),
    ...(values.authType === "oauth" && values.clientSecret.trim()
      ? { client_secret: values.clientSecret.trim() }
      : {}),
    ...(options.isAdmin ? { team_enabled: values.teamEnabled } : {}),
    ...(options.canManageAgentAccess ? { agent_scope: values.agentScope } : {}),
  };
}
