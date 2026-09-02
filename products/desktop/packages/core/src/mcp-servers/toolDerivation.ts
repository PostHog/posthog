import type {
  McpApprovalState,
  McpInstallationTool,
} from "@posthog/api-client/types";

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
