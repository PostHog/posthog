// Shared types for MCP server installations and marketplace templates.
// Mirrors the PostHog cloud REST schema (see `apps/code/src/renderer/api/generated.ts`).

export type McpAuthType = "api_key" | "oauth" | "none";

export type McpApprovalState = "approved" | "needs_approval" | "do_not_use";

export type McpInstallSource = "posthog" | "posthog-code" | "posthog-mobile";

/** Server-side marketplace template — one entry per recommended server. */
export interface McpRecommendedServer {
  id: string;
  name: string;
  url: string;
  docs_url?: string;
  description?: string;
  auth_type?: McpAuthType;
  /** The vendor's brand domain (e.g. "linear.app"), rendered via the
   *  logo.dev icon proxy. Empty when no brand icon is known. */
  icon_domain?: string;
  category?: string;
  /** Some templates expose a `transport_type` ("stdio" | "streamable_http"); when
   *  absent, treat as HTTP. Stdio servers can't run on mobile; we badge them. */
  transport_type?: "stdio" | "streamable_http";
}

/** Server-side record of one user's installation of a server. */
export interface McpServerInstallation {
  id: string;
  template_id: string | null;
  name: string;
  /** Brand domain from the linked template, rendered via the logo.dev icon
   *  proxy. Empty if custom install (no template). */
  icon_domain?: string;
  display_name?: string;
  url?: string;
  description?: string;
  auth_type?: McpAuthType;
  is_enabled?: boolean;
  needs_reauth: boolean;
  pending_oauth: boolean;
  /** Cloud-hosted proxy URL the client should hit to talk to the MCP server.
   *  Desktop substitutes a local loopback; mobile uses whatever the API returns. */
  proxy_url: string;
  tool_count: number;
  transport_type?: "stdio" | "streamable_http";
  created_at: string;
  updated_at: string | null;
}

export interface McpInstallationTool {
  id: string;
  tool_name: string;
  display_name: string;
  description: string;
  input_schema: unknown;
  approval_state?: McpApprovalState;
  last_seen_at: string;
  removed_at: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface McpOAuthRedirectResponse {
  redirect_url: string;
}

export type McpInstallResponse =
  | McpServerInstallation
  | McpOAuthRedirectResponse;

export function isOAuthRedirect(
  response: McpInstallResponse,
): response is McpOAuthRedirectResponse {
  return (
    typeof (response as McpOAuthRedirectResponse).redirect_url === "string"
  );
}

export interface InstallCustomMcpServerOptions {
  name: string;
  url: string;
  auth_type: McpAuthType;
  api_key?: string;
  description?: string;
  client_id?: string;
  client_secret?: string;
  install_source?: McpInstallSource;
  posthog_code_callback_url?: string;
}

export interface InstallMcpTemplateOptions {
  template_id: string;
  api_key?: string;
  install_source?: McpInstallSource;
  posthog_code_callback_url?: string;
}

export interface UpdateMcpServerInstallationOptions {
  display_name?: string;
  description?: string;
  is_enabled?: boolean;
}

export interface McpUiResource {
  uri: string;
  html: string;
  /** Opaque CSP descriptor handed straight to AppBridge (`McpUiResourceCsp`). */
  csp?: Record<string, unknown>;
  permissions?: Record<string, Record<string, unknown>>;
}

/** Returns true if the template/installation requires stdio transport, which
 *  the mobile app can't host. UI uses this to render a "Desktop only" badge. */
export function isStdioServer(
  s: Pick<McpRecommendedServer | McpServerInstallation, "transport_type">,
): boolean {
  return s.transport_type === "stdio";
}
