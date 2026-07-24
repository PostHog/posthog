import { authedFetch, getBaseUrl, getProjectId } from "@/lib/api";
import type {
  InstallCustomMcpServerOptions,
  InstallMcpTemplateOptions,
  McpApprovalState,
  McpInstallationTool,
  McpInstallResponse,
  McpOAuthRedirectResponse,
  McpRecommendedServer,
  McpServerInstallation,
  UpdateMcpServerInstallationOptions,
} from "./types";

function mcpBaseUrl(): string {
  const base = getBaseUrl();
  const projectId = getProjectId();
  return `${base}/api/environments/${projectId}/mcp_server_installations`;
}

async function readJsonOrThrow<T>(
  response: Response,
  errorPrefix: string,
): Promise<T> {
  if (!response.ok) {
    const data = (await response.json().catch(() => ({}))) as {
      detail?: string;
    };
    throw new Error(data.detail ?? `${errorPrefix}: ${response.statusText}`);
  }
  return (await response.json()) as T;
}

/** GET /api/environments/{teamId}/mcp_servers/ — marketplace templates. */
export async function getMcpRecommendedServers(): Promise<
  McpRecommendedServer[]
> {
  const base = getBaseUrl();
  const projectId = getProjectId();
  const response = await authedFetch(
    `${base}/api/environments/${projectId}/mcp_servers/`,
  );
  const data = await readJsonOrThrow<
    McpRecommendedServer[] | { results?: McpRecommendedServer[] }
  >(response, "Failed to fetch MCP servers");
  return Array.isArray(data) ? data : (data.results ?? []);
}

/** GET /api/environments/{teamId}/mcp_server_installations/ */
export async function getMcpServerInstallations(): Promise<
  McpServerInstallation[]
> {
  const response = await authedFetch(`${mcpBaseUrl()}/`);
  const data = await readJsonOrThrow<
    McpServerInstallation[] | { results?: McpServerInstallation[] }
  >(response, "Failed to fetch MCP server installations");
  return Array.isArray(data) ? data : (data.results ?? []);
}

/** POST /api/environments/{teamId}/mcp_server_installations/install_custom/ */
export async function installCustomMcpServer(
  options: InstallCustomMcpServerOptions,
): Promise<McpInstallResponse> {
  const response = await authedFetch(`${mcpBaseUrl()}/install_custom/`, {
    method: "POST",
    body: JSON.stringify(options),
  });
  return readJsonOrThrow<McpInstallResponse>(
    response,
    "Failed to install MCP server",
  );
}

/** POST /api/environments/{teamId}/mcp_server_installations/install_template/ */
export async function installMcpTemplate(
  options: InstallMcpTemplateOptions,
): Promise<McpInstallResponse> {
  const response = await authedFetch(`${mcpBaseUrl()}/install_template/`, {
    method: "POST",
    body: JSON.stringify(options),
  });
  return readJsonOrThrow<McpInstallResponse>(
    response,
    "Failed to install MCP template",
  );
}

/** PATCH /api/environments/{teamId}/mcp_server_installations/{id}/ */
export async function updateMcpServerInstallation(
  installationId: string,
  updates: UpdateMcpServerInstallationOptions,
): Promise<McpServerInstallation> {
  const response = await authedFetch(`${mcpBaseUrl()}/${installationId}/`, {
    method: "PATCH",
    body: JSON.stringify(updates),
  });
  return readJsonOrThrow<McpServerInstallation>(
    response,
    "Failed to update MCP server",
  );
}

/** DELETE /api/environments/{teamId}/mcp_server_installations/{id}/ */
export async function uninstallMcpServer(
  installationId: string,
): Promise<void> {
  const response = await authedFetch(`${mcpBaseUrl()}/${installationId}/`, {
    method: "DELETE",
  });
  if (!response.ok && response.status !== 204) {
    throw new Error(`Failed to uninstall MCP server: ${response.statusText}`);
  }
}

/** GET /api/environments/{teamId}/mcp_server_installations/authorize/?installation_id={id} */
export async function authorizeMcpInstallation(options: {
  installation_id: string;
  install_source?: "posthog" | "posthog-code" | "posthog-mobile";
  posthog_code_callback_url?: string;
}): Promise<McpOAuthRedirectResponse> {
  const params = new URLSearchParams();
  params.set("installation_id", options.installation_id);
  if (options.install_source) {
    params.set("install_source", options.install_source);
  }
  if (options.posthog_code_callback_url) {
    params.set("posthog_code_callback_url", options.posthog_code_callback_url);
  }
  const response = await authedFetch(
    `${mcpBaseUrl()}/authorize/?${params.toString()}`,
  );
  return readJsonOrThrow<McpOAuthRedirectResponse>(
    response,
    "Failed to authorize MCP installation",
  );
}

/** GET /api/environments/{teamId}/mcp_server_installations/{id}/tools/ */
export async function getMcpInstallationTools(
  installationId: string,
  options: { includeRemoved?: boolean } = {},
): Promise<McpInstallationTool[]> {
  const params = new URLSearchParams();
  if (options.includeRemoved) params.set("include_removed", "1");
  const query = params.toString();
  const response = await authedFetch(
    `${mcpBaseUrl()}/${installationId}/tools/${query ? `?${query}` : ""}`,
  );
  const data = await readJsonOrThrow<
    McpInstallationTool[] | { results?: McpInstallationTool[] }
  >(response, "Failed to fetch MCP installation tools");
  return Array.isArray(data) ? data : (data.results ?? []);
}

/** PATCH /api/environments/{teamId}/mcp_server_installations/{id}/tools/{name}/ */
export async function updateMcpToolApproval(
  installationId: string,
  toolName: string,
  approval_state: McpApprovalState,
): Promise<McpInstallationTool> {
  const response = await authedFetch(
    `${mcpBaseUrl()}/${installationId}/tools/${encodeURIComponent(toolName)}/`,
    {
      method: "PATCH",
      body: JSON.stringify({ approval_state }),
    },
  );
  return readJsonOrThrow<McpInstallationTool>(
    response,
    "Failed to update tool approval",
  );
}

/** POST /api/environments/{teamId}/mcp_server_installations/{id}/tools/refresh/ */
export async function refreshMcpInstallationTools(
  installationId: string,
): Promise<McpInstallationTool[]> {
  const response = await authedFetch(
    `${mcpBaseUrl()}/${installationId}/tools/refresh/`,
    { method: "POST" },
  );
  const data = await readJsonOrThrow<
    McpInstallationTool[] | { results?: McpInstallationTool[] }
  >(response, "Failed to refresh MCP tools");
  return Array.isArray(data) ? data : (data.results ?? []);
}
