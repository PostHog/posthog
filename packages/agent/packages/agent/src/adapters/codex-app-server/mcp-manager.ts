/** An MCP tool call codex is running: its server, tool, and arguments. */
export interface McpCall {
  server: string;
  tool: string;
  args: unknown;
}

interface McpItem {
  id: string;
  server: string;
  tool: string;
  arguments: unknown;
}

function readMcpItem(params: unknown): McpItem | null {
  const item = (
    params as {
      item?: {
        type?: string;
        id?: string;
        server?: string;
        tool?: string;
        arguments?: unknown;
      };
    }
  )?.item;
  if (item?.type === "mcpToolCall" && item.id && item.server && item.tool) {
    return {
      id: item.id,
      server: item.server,
      tool: item.tool,
      arguments: item.arguments,
    };
  }
  return null;
}

/**
 * Correlates codex approval prompts back to the MCP tool that triggered them: by
 * item id for a command approval, or by server name for an elicitation (which
 * carries no id, so it maps to the latest in-flight call — MCP calls are sequential).
 */
export class McpManager {
  private readonly byId = new Map<string, McpCall>();
  private latest?: McpCall;

  /** Record an `mcpToolCall` item from an item/started notification. */
  capture(params: unknown): void {
    const item = readMcpItem(params);
    if (!item) return;
    const call: McpCall = {
      server: item.server,
      tool: item.tool,
      args: item.arguments,
    };
    this.byId.set(item.id, call);
    this.latest = call;
  }

  /**
   * Evict on item/completed — approvals only arrive while a call is in flight,
   * and keeping every finished call would grow the map for the session's lifetime.
   */
  release(params: unknown): void {
    const item = readMcpItem(params);
    if (!item) return;
    const call = this.byId.get(item.id);
    this.byId.delete(item.id);
    if (call && this.latest === call) this.latest = undefined;
  }

  /** The MCP call for a command-execution approval's item id, if known. */
  byItemId(itemId: string | undefined): McpCall | undefined {
    return itemId ? this.byId.get(itemId) : undefined;
  }

  /** The in-flight MCP call for an elicitation's server (elicitations carry no item id). */
  byServer(serverName: string): McpCall | undefined {
    return this.latest?.server === serverName ? this.latest : undefined;
  }
}
