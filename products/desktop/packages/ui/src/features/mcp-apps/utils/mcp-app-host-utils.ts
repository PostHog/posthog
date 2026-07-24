/**
 * Shared utilities for McpAppHost: container dimension calculations
 * for inline/fullscreen display modes.
 *
 * @see https://modelcontextprotocol.io/specification/2025-03-26/extensions/mcp-apps
 */

import type { McpUiDisplayMode } from "@modelcontextprotocol/ext-apps/app-bridge";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";

export const INLINE_MAX_HEIGHT = 600;
export const FULLSCREEN_HEADER_HEIGHT = 48;
export const FULLSCREEN_PADDING = 32;

export interface ContainerDimensions {
  width: number;
  height?: number;
  maxHeight?: number;
}

export function parseMcpToolKey(mcpToolName: string): {
  serverName: string;
  toolName: string;
} {
  const parts = mcpToolName.split("__");
  return {
    serverName: parts[1] ?? "",
    toolName: parts.slice(2).join("__"),
  };
}

/**
 * Safely converts an unknown rawOutput into a well-formed CallToolResult.
 * The ACP SDK types rawOutput as `unknown`; this normalizes whatever arrives
 * so the MCP App bridge always receives valid data.
 *
 * The Anthropic API can return `mcp_tool_result.content` as either a string
 * or an array. The Claude Agent SDK builds `tool_use_result` as:
 *   { content: toolUseResult, ...mcpMeta }
 * where `mcpMeta` may contain `structuredContent` and `_meta`.
 *
 * This function ensures `content` is always an array while preserving all
 * other fields (structuredContent, _meta, isError) from the raw result.
 */
export function toCallToolResult(raw: unknown): CallToolResult {
  if (raw != null && typeof raw === "object" && "content" in raw) {
    const obj = raw as { content: unknown };
    if (Array.isArray(obj.content)) {
      return raw as CallToolResult;
    }
    // content exists but isn't an array — normalize to text block array
    // while preserving structuredContent, _meta, isError, etc.
    const text =
      typeof obj.content === "string"
        ? obj.content
        : JSON.stringify(obj.content);
    return {
      ...(raw as CallToolResult),
      content: [{ type: "text", text }],
    };
  }

  // Wrap primitives (e.g. a bare string) into the expected shape
  const text =
    typeof raw === "string" ? raw : raw != null ? JSON.stringify(raw) : "";
  return {
    content: [{ type: "text", text }],
  };
}

export function computeContainerDimensions(
  mode: McpUiDisplayMode,
  inlineWidth: number,
  viewportWidth = window.innerWidth,
  viewportHeight = window.innerHeight,
): ContainerDimensions {
  if (mode === "fullscreen") {
    return {
      width: Math.max(0, viewportWidth - FULLSCREEN_PADDING),
      height: Math.max(
        0,
        viewportHeight - FULLSCREEN_HEADER_HEIGHT - FULLSCREEN_PADDING,
      ),
    };
  }
  return {
    width: inlineWidth,
    maxHeight: INLINE_MAX_HEIGHT,
  };
}
