import type {
  McpUiResourceCsp,
  McpUiResourcePermissions,
} from "@modelcontextprotocol/ext-apps/app-bridge";
import { z } from "zod";

// --- UI Resources ---

export const mcpUiResourceSchema = z.object({
  uri: z.string(),
  name: z.string().optional(),
  mimeType: z.string(),
  csp: z
    .object({
      connectDomains: z.array(z.string()).optional(),
      resourceDomains: z.array(z.string()).optional(),
      frameDomains: z.array(z.string()).optional(),
      baseUriDomains: z.array(z.string()).optional(),
    })
    .optional(),
  permissions: z
    .object({
      camera: z.object({}).optional(),
      microphone: z.object({}).optional(),
      geolocation: z.object({}).optional(),
      clipboardWrite: z.object({}).optional(),
    })
    .optional(),
  html: z.string(),
  serverName: z.string(),
});

export interface McpUiResource {
  uri: string;
  name?: string;
  mimeType: string;
  csp?: McpUiResourceCsp;
  permissions?: McpUiResourcePermissions;
  html: string;
  serverName: string;
}

// --- MCP extension metadata shapes ---
// The MCP SDK types don't expose the `_meta.ui` extension fields, so we define
// them here for use when casting raw SDK tool/resource objects.

export type McpToolUiVisibility = "model" | "app";

export const LEGACY_RESOURCE_URI_META_KEY = "ui/resourceUri";

/** Shape of UI metadata on MCP tool definitions. */
export interface McpToolUiMeta {
  _meta?: {
    ui?: {
      resourceUri?: string;
      visibility?: McpToolUiVisibility[];
    };
    [LEGACY_RESOURCE_URI_META_KEY]?: string;
  };
}

export interface McpToolRegistrationMetadata {
  resourceUri?: string;
  visibility: McpToolUiVisibility[];
}

const DEFAULT_TOOL_VISIBILITY: McpToolUiVisibility[] = ["model", "app"];

/**
 * Registration metadata supports both resource URI formats, while visibility
 * defaults to both callers when the server omits it, as required by MCP Apps.
 */
export function resolveToolRegistrationMetadata(
  tool: unknown,
): McpToolRegistrationMetadata {
  if (tool == null || typeof tool !== "object") {
    return { visibility: [...DEFAULT_TOOL_VISIBILITY] };
  }

  const meta = (tool as McpToolUiMeta)._meta;
  const modernResourceUri = meta?.ui?.resourceUri;
  const legacyResourceUri = meta?.[LEGACY_RESOURCE_URI_META_KEY];
  const resourceUri =
    typeof modernResourceUri === "string" && modernResourceUri.length > 0
      ? modernResourceUri
      : typeof legacyResourceUri === "string" && legacyResourceUri.length > 0
        ? legacyResourceUri
        : undefined;

  const declaredVisibility = meta?.ui?.visibility;
  const visibility =
    declaredVisibility === undefined
      ? [...DEFAULT_TOOL_VISIBILITY]
      : Array.isArray(declaredVisibility)
        ? declaredVisibility.filter(
            (value): value is McpToolUiVisibility =>
              value === "model" || value === "app",
          )
        : [];

  return { resourceUri, visibility };
}

/** Shape of MCP resource definitions that carry `_meta.ui` CSP/permissions. */
export interface McpResourceUiMeta {
  uri: string;
  name?: string;
  _meta?: {
    ui?: {
      csp?: McpUiResource["csp"];
      permissions?: McpUiResource["permissions"];
    };
  };
}

// --- Built-in PostHog MCP server (single `exec` tool) ---
//
// The built-in PostHog MCP server is registered under this name (see
// `AgentAuthAdapter.buildMcpServers`). Unlike the MCP Apps spec — which binds a
// tool to its UI app upfront via the tool's registration `_meta.ui.resourceUri`
// — PostHog surfaces every UI app through a single generic `exec` tool and rides
// the `resourceUri` on each *tool-call response* `_meta` instead. Discovery via
// `listTools()` therefore never sees it, so for this server + tool the host has
// to resolve the UI app per call from the result metadata.
export const BUILTIN_POSTHOG_SERVER_NAME = "posthog";
export const EXEC_TOOL_NAME = "exec";
export const POSTHOG_EXEC_TOOL_KEY = `mcp__${BUILTIN_POSTHOG_SERVER_NAME}__${EXEC_TOOL_NAME}`;

/**
 * Resolve a UI resource URI from a tool-call response, preferring the modern
 * nested `_meta.ui.resourceUri` and falling back to the legacy flat key —
 * matching the host-side resolution recommended by `@modelcontextprotocol/ext-apps`.
 * Returns `undefined` when the result carries no UI resource.
 */
export function resolveResultResourceUri(result: unknown): string | undefined {
  if (result == null || typeof result !== "object") return undefined;
  const meta = (result as { _meta?: Record<string, unknown> })._meta;
  if (meta == null || typeof meta !== "object") return undefined;
  const ui = (meta as { ui?: { resourceUri?: unknown } }).ui;
  const modern = ui?.resourceUri;
  if (typeof modern === "string" && modern.length > 0) return modern;
  const legacy = (meta as Record<string, unknown>)[
    LEGACY_RESOURCE_URI_META_KEY
  ];
  return typeof legacy === "string" && legacy.length > 0 ? legacy : undefined;
}

/** Tool-to-UI associations */
export const mcpToolUiAssociationSchema = z.object({
  toolKey: z.string(),
  serverName: z.string(),
  toolName: z.string(),
  resourceUri: z.string(),
  visibility: z.array(z.enum(["model", "app"])).optional(),
});

export type McpToolUiAssociation = z.infer<typeof mcpToolUiAssociationSchema>;

// --- tRPC input/output schemas ---

export const getUiResourceInput = z.object({
  toolKey: z.string(),
});

export const hasUiForToolInput = z.object({
  toolKey: z.string(),
});

export const getToolDefinitionInput = z.object({
  toolKey: z.string(),
});

export const proxyToolCallInput = z.object({
  serverName: z.string(),
  toolName: z.string(),
  args: z.record(z.string(), z.unknown()).optional(),
});

export const proxyResourceReadInput = z.object({
  serverName: z.string(),
  uri: z.string(),
});

export const openLinkInput = z.object({
  url: z.string(),
});

export const mcpAppsSubscriptionInput = z.object({
  toolKey: z.string(),
});

/**
 * Fetch a UI resource directly by URI. Used by the built-in PostHog `exec`
 * path, where the renderer resolves the `ui://` URI from the tool result's
 * `_meta` (see {@link resolveResultResourceUri}) rather than a registered
 * tool->UI association.
 */
export const getUiResourceByUriInput = z.object({
  serverName: z.string(),
  resourceUri: z.string(),
});

// --- Service event types ---

export interface McpAppsToolInputEvent {
  toolKey: string;
  toolCallId: string;
  args: unknown;
}

export interface McpAppsToolResultEvent {
  toolKey: string;
  toolCallId: string;
  result: unknown;
  isError?: boolean;
}

export interface McpAppsToolCancelledEvent {
  toolKey: string;
  toolCallId: string;
}

export interface McpAppsDiscoveryCompleteEvent {
  toolKeys: string[];
}

export const McpAppsServiceEvent = {
  ToolInput: "tool-input",
  ToolResult: "tool-result",
  ToolCancelled: "tool-cancelled",
  DiscoveryComplete: "discovery-complete",
} as const;

export interface McpAppsServiceEvents {
  [McpAppsServiceEvent.ToolInput]: McpAppsToolInputEvent;
  [McpAppsServiceEvent.ToolResult]: McpAppsToolResultEvent;
  [McpAppsServiceEvent.ToolCancelled]: McpAppsToolCancelledEvent;
  [McpAppsServiceEvent.DiscoveryComplete]: McpAppsDiscoveryCompleteEvent;
}

// --- MCP server connection config ---

export interface McpServerConnectionConfig {
  name: string;
  url: string;
  headers: Record<string, string>;
}
