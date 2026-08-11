import type {
  McpAuthType,
  McpGatewayServer,
} from "@posthog/api-client/posthog-client";
import {
  type InstallFlowClient,
  type IOAuthCallback,
  installCustomWithOAuth,
  installTemplateWithOAuth,
  type OAuthCallbackResult,
} from "../mcp-servers/installFlow";

/** Personal credentials a member supplies when connecting to a gateway server. */
export interface GatewayConnectCredentials {
  authType: McpAuthType;
  apiKey: string;
  /** Optional OAuth client for providers without dynamic client registration. */
  clientId: string;
  clientSecret: string;
}

export const GATEWAY_CONNECT_DEFAULTS: GatewayConnectCredentials = {
  authType: "oauth",
  apiKey: "",
  clientId: "",
  clientSecret: "",
};

type GatewayConnectServer = Pick<
  McpGatewayServer,
  "template_id" | "template_auth_type"
>;

/**
 * The auth mechanism a connection must use: catalog templates fix it, custom
 * servers leave it null — every credential is personal, so each member picks
 * their own mechanism when they connect.
 */
export function gatewayConnectAuthType(
  server: GatewayConnectServer,
): McpAuthType | null {
  return server.template_id ? (server.template_auth_type ?? "oauth") : null;
}

/**
 * OAuth connects need no input up front — the browser round-trip collects the
 * grant. Everything else (API-key templates, custom servers where the member
 * chooses) must collect credentials before installing.
 */
export function gatewayConnectNeedsCredentials(
  server: GatewayConnectServer,
): boolean {
  return gatewayConnectAuthType(server) !== "oauth";
}

/** Same decision for a catalog template with no gateway row yet. */
export function templateConnectNeedsCredentials(template: {
  auth_type?: McpAuthType;
}): boolean {
  return (template.auth_type ?? "oauth") !== "oauth";
}

export function canSubmitGatewayConnect(
  credentials: Pick<GatewayConnectCredentials, "authType" | "apiKey">,
): boolean {
  return credentials.authType !== "api_key" || credentials.apiKey.trim() !== "";
}

export interface GatewayConnectTarget {
  template_id: string | null;
  name: string;
  url: string;
  description: string;
}

/**
 * Connect the caller's own credential to a gateway server, or to a catalog
 * template with no row yet — the backend materializes the row. Honors the
 * chosen auth mechanism instead of assuming OAuth: API-key connects complete
 * inline, OAuth connects round-trip the host browser callback.
 */
export async function connectGatewayServer(
  client: InstallFlowClient,
  oauth: IOAuthCallback,
  target: GatewayConnectTarget,
  credentials: GatewayConnectCredentials = GATEWAY_CONNECT_DEFAULTS,
): Promise<OAuthCallbackResult> {
  const apiKey =
    credentials.authType === "api_key" && credentials.apiKey
      ? credentials.apiKey
      : undefined;
  if (target.template_id) {
    return installTemplateWithOAuth(client, oauth, {
      template_id: target.template_id,
      api_key: apiKey,
    });
  }
  return installCustomWithOAuth(client, oauth, {
    name: target.name,
    url: target.url,
    description: target.description,
    auth_type: credentials.authType,
    api_key: apiKey,
    client_id:
      credentials.authType === "oauth" && credentials.clientId.trim()
        ? credentials.clientId.trim()
        : undefined,
    client_secret:
      credentials.authType === "oauth" && credentials.clientSecret.trim()
        ? credentials.clientSecret.trim()
        : undefined,
  });
}
