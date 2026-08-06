import "./generated.augment";
import type { Schemas } from "./generated";

export type McpCategory = Schemas.CategoryEnum;
export type McpApprovalState =
  Schemas.MCPServerInstallationToolApprovalStateEnum;
export type McpAuthType = Schemas.MCPAuthTypeEnum;
export type McpRecommendedServer = Schemas.MCPServerTemplate;
export type McpServerInstallation = Schemas.MCPServerInstallation & {
  scope?: "personal" | "shared";
};
export type McpInstallationTool = Schemas.MCPServerInstallationTool & {
  /** Team-admin ceiling returned by gateway-aware backends. */
  team_state?: McpApprovalState | null;
  locked?: boolean;
  decided_by?: "rule" | "scope" | "team" | "preset" | "legacy" | "default";
};
export type McpOAuthRedirectResponse = Schemas.OAuthRedirectResponse;
export type McpInstallSource = "posthog" | "posthog-code" | "posthog-mobile";
export type McpInstallResponse =
  | McpServerInstallation
  | McpOAuthRedirectResponse;

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
