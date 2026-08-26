import type {
  McpApprovalState,
  McpInstallationTool,
} from "@posthog/api-client/types";

export type ToolCategory = "read" | "write";

const READ_PREFIXES = [
  "get",
  "list",
  "read",
  "search",
  "find",
  "query",
  "fetch",
  "lookup",
  "check",
  "has",
  "is",
  "can",
  "count",
  "exists",
  "describe",
  "info",
  "status",
  "head",
];

const WRITE_PREFIXES = [
  "create",
  "update",
  "modify",
  "write",
  "edit",
  "delete",
  "remove",
  "destroy",
  "insert",
  "add",
  "set",
  "put",
  "post",
  "patch",
  "send",
  "execute",
  "run",
  "invoke",
  "call",
  "apply",
  "move",
  "copy",
  "rename",
];

/**
 * Categorize a tool as "read" or "write" based on its name.
 * Tools with ambiguous or unknown names default to "write" (safer to require approval).
 */
export function categorizeTool(toolName: string): ToolCategory {
  const lower = toolName.toLowerCase();

  for (const prefix of READ_PREFIXES) {
    if (lower.startsWith(prefix)) {
      return "read";
    }
  }

  for (const prefix of WRITE_PREFIXES) {
    if (lower.startsWith(prefix)) {
      return "write";
    }
  }

  return "write";
}

export interface ToolGroup {
  category: ToolCategory;
  label: string;
  tools: McpInstallationTool[];
}

const CATEGORY_LABELS: Record<ToolCategory, string> = {
  read: "Read tools",
  write: "Write / Delete tools",
};

/**
 * Group tools by read/write category, preserving alphabetical order within each group.
 */
export function groupToolsByCategory(
  tools: McpInstallationTool[],
): ToolGroup[] {
  const readTools: McpInstallationTool[] = [];
  const writeTools: McpInstallationTool[] = [];

  for (const tool of tools) {
    if (tool.removed_at) continue;
    const category = categorizeTool(tool.tool_name);
    if (category === "read") {
      readTools.push(tool);
    } else {
      writeTools.push(tool);
    }
  }

  readTools.sort((a, b) => a.tool_name.localeCompare(b.tool_name));
  writeTools.sort((a, b) => a.tool_name.localeCompare(b.tool_name));

  const groups: ToolGroup[] = [];
  if (readTools.length > 0) {
    groups.push({ category: "read", label: CATEGORY_LABELS.read, tools: readTools });
  }
  if (writeTools.length > 0) {
    groups.push({ category: "write", label: CATEGORY_LABELS.write, tools: writeTools });
  }
  return groups;
}

export function countToolsByApproval(
  tools: McpInstallationTool[],
): Record<McpApprovalState, number> {
  return tools.reduce(
    (acc, t) => {
      if (t.removed_at || !t.approval_state) return acc;
      acc[t.approval_state] = (acc[t.approval_state] ?? 0) + 1;
      return acc;
    },
    {} as Record<McpApprovalState, number>,
  );
}

export function sortToolsForDisplay(
  tools: McpInstallationTool[],
): McpInstallationTool[] {
  return [...tools].sort((a, b) => {
    if (!!a.removed_at !== !!b.removed_at) {
      return a.removed_at ? 1 : -1;
    }
    return a.tool_name.localeCompare(b.tool_name);
  });
}

export function filterToolsByName(
  tools: McpInstallationTool[],
  term: string,
): McpInstallationTool[] {
  const q = term.trim().toLowerCase();
  if (!q) return tools;
  return tools.filter((t) => t.tool_name.toLowerCase().includes(q));
}

export function countActiveTools(tools: McpInstallationTool[]): number {
  return tools.filter((t) => !t.removed_at).length;
}

export function countRemovedTools(tools: McpInstallationTool[]): number {
  return tools.filter((t) => !!t.removed_at).length;
}
