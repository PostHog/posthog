/** Footer rendering for active standalone subagents and workflows. */
import type { Theme } from "@earendil-works/pi-coding-agent";
import { truncateToWidth } from "@earendil-works/pi-tui";
import { listWorkflows } from "../workflow/status-registry";
import { formatUsageStats } from "./render";
import {
  getCumulativeUsage,
  getFocusedWorkflowId,
  isFocused,
  listAgentRuns,
} from "./status-registry";

const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

export function renderSubagentFooterLines(
  theme: Theme,
  width: number,
  spinnerFrame: number,
): string[] {
  const runs = listAgentRuns();
  const workflows = listWorkflows();
  if (runs.length === 0 && workflows.length === 0) return [];
  const spinner = theme.fg(
    "accent",
    SPINNER_FRAMES[spinnerFrame % SPINNER_FRAMES.length],
  );
  const focused = isFocused();
  const workflowFocus = getFocusedWorkflowId();
  const lines: string[] = [];
  if (runs.length > 0) {
    const usageStr = formatUsageStats(getCumulativeUsage());
    const line = `${workflowFocus ? "  " : focused ? theme.fg("accent", theme.bold("▶ ")) : "  "}${spinner} ${theme.fg("accent", `${runs.length} subagent${runs.length > 1 ? "s" : ""} running`)}${usageStr ? theme.fg("dim", ` · ${usageStr}`) : ""}`;
    lines.push(
      truncateToWidth(
        !workflowFocus && focused ? theme.bg("selectedBg", line) : line,
        width,
      ),
    );
  }
  for (const workflow of workflows) {
    const done = workflow.agents.filter(
      (agent) => agent.status !== "running",
    ).length;
    const selected = workflowFocus === workflow.workflowId;
    const line = `${selected ? theme.fg("accent", theme.bold("▶ ")) : "  "}${spinner} ${theme.fg("accent", workflow.name ?? "workflow")} ${theme.fg("dim", `${done}/${workflow.agents.length} agents`)}`;
    lines.push(
      truncateToWidth(selected ? theme.bg("selectedBg", line) : line, width),
    );
  }
  lines.push(
    truncateToWidth(
      theme.fg(
        "dim",
        focused
          ? "  ↑/↓ move · enter open · esc back to editor"
          : "  ↓ from an empty editor to focus",
      ),
      width,
    ),
  );
  return lines;
}
