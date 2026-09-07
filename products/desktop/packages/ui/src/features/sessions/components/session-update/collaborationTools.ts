const SUBAGENT_SPAWN_TOOL_NAMES = new Set<string>([
  "Task",
  "Agent",
  "spawn_agent",
  "subagent",
]);

export function isSubagentSpawnTool(
  toolName: string | null | undefined,
): boolean {
  return (
    SUBAGENT_SPAWN_TOOL_NAMES.has(toolName ?? "") ||
    toolName?.toLowerCase() === "subagent"
  );
}

const WORKFLOW_TOOL_NAMES = new Set<string>(["workflow"]);

export function isWorkflowTool(toolName: string | null | undefined): boolean {
  return WORKFLOW_TOOL_NAMES.has(toolName?.toLowerCase() ?? "");
}

const PLAN_APPROVAL_TOOL_NAMES = new Set<string>(["ExitPlanMode"]);

export function isPlanApprovalTool(toolName: string | undefined): boolean {
  return PLAN_APPROVAL_TOOL_NAMES.has(toolName ?? "");
}
