import type {
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
  /** Team sharing is admin-only; agent sharing follows the team setting. */
  teamEnabled: boolean;
  /** Agents turned off by the installer. Every other agent is shared with. */
  excludedAgentIds: string[];
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
  excludedAgentIds: [],
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
 * attached only for admins; agent grants are attached whenever the team
 * allows this member to manage agent access.
 *
 * A new server is shared with every agent by default. The explicit list is only
 * sent once the agent catalog has loaded, so turning every agent off still means
 * "none"; until then the field is omitted and the backend applies the same
 * all-agents default.
 */
export function buildGatewayInstallRequest(
  values: GatewayAddServerValues,
  options: {
    isAdmin: boolean;
    canManageAgentAccess: boolean;
    /** Every agent available to the project. */
    agentIds: string[];
  },
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
    ...(options.canManageAgentAccess && options.agentIds.length
      ? {
          agent_ids: options.agentIds.filter(
            (id) => !values.excludedAgentIds.includes(id),
          ),
        }
      : {}),
  };
}
