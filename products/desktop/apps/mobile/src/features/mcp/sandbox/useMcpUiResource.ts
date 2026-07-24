import {
  getToolUiResourceUri,
  RESOURCE_MIME_TYPE,
} from "@modelcontextprotocol/ext-apps/app-bridge";
import type { Tool } from "@modelcontextprotocol/sdk/types.js";
import { useQuery } from "@tanstack/react-query";
import { getMcpConnectionManager } from "../service";
import type { McpServerInstallation, McpUiResource } from "../types";

interface UseMcpUiResourceArgs {
  installation: McpServerInstallation | null;
  toolName: string;
}

interface UiResourceBundle {
  resource: McpUiResource;
  tool: Tool;
}

/**
 * Resolve the MCP App UI resource for a given installation + tool. Connects
 * to the MCP server (lazy, cached), lists its tools to find the UI URI on
 * `_meta.ui.resourceUri`, then reads the resource and returns its HTML
 * payload alongside the tool definition.
 */
export function useMcpUiResource({
  installation,
  toolName,
}: UseMcpUiResourceArgs) {
  return useQuery<UiResourceBundle | null>({
    queryKey: ["mcp", "ui-resource", installation?.id ?? null, toolName],
    queryFn: async () => {
      if (!installation) return null;
      const manager = getMcpConnectionManager();
      const args = {
        installationId: installation.id,
        serverName: installation.name,
        proxyUrl: installation.proxy_url,
      };
      const tool = await manager.getTool({ ...args, toolName });
      if (!tool) return null;
      const uri = getToolUiResourceUri(tool);
      if (!uri) return null;

      const readResult = await manager.readResource({ ...args, uri });
      const contents = readResult.contents.find((c) => c.uri === uri) as
        | (Record<string, unknown> & { uri: string })
        | undefined;
      const textValue = contents
        ? (contents as { text?: unknown }).text
        : undefined;
      const text = typeof textValue === "string" ? textValue : null;
      if (!text) return null;

      const mimeValue = contents
        ? (contents as { mimeType?: unknown }).mimeType
        : undefined;
      const mime = typeof mimeValue === "string" ? mimeValue : "";
      if (!mime.includes(RESOURCE_MIME_TYPE.split(";")[0])) {
        // Resource doesn't look like an MCP App profile — skip rather than
        // mount arbitrary HTML.
        return null;
      }

      const meta = (contents as { _meta?: Record<string, unknown> })._meta;
      const ui = (meta?.ui as Record<string, unknown>) ?? {};
      const permissions =
        (ui.permissions as Record<string, Record<string, unknown>>) ??
        undefined;
      const csp = (ui.csp as Record<string, unknown> | undefined) ?? undefined;

      return {
        resource: { uri, html: text, csp, permissions },
        tool,
      };
    },
    enabled: !!installation,
    staleTime: 5 * 60 * 1000,
  });
}
