export const SUBAGENT_SPAWN_TOOL_NAMES = new Set<string>([
  "Task",
  "Agent",
  "spawn_agent",
]);

export function isSubagentSpawnTool(toolName: string | undefined): boolean {
  return SUBAGENT_SPAWN_TOOL_NAMES.has(toolName ?? "");
}

/**
 * The plan-approval tool. Its call carries the plan the user reads and approves
 * before the agent leaves plan mode, so the thread surfaces it as its own plan
 * card (PlanApprovalView) and never folds it into a collapsed tool group.
 *
 * Detected by name, not only by the `switch_mode` kind: a plan can reach the
 * thread before its kind resolves (the call is emitted from the model's raw
 * input, and the plan/kind are backfilled by the permission handler), and
 * grouping keyed on kind alone then buries it. Name is set on every emission
 * path from the first frame, so it is the stable signal.
 */
export const PLAN_APPROVAL_TOOL_NAMES = new Set<string>(["ExitPlanMode"]);

export function isPlanApprovalTool(toolName: string | undefined): boolean {
  return PLAN_APPROVAL_TOOL_NAMES.has(toolName ?? "");
}
