export const SUBAGENT_SPAWN_TOOL_NAMES = new Set<string>([
  "Task",
  "Agent",
  "spawn_agent",
]);

export function isSubagentSpawnTool(toolName: string | undefined): boolean {
  return SUBAGENT_SPAWN_TOOL_NAMES.has(toolName ?? "");
}
