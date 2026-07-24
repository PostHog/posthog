/** Live detail overlay for one active workflow. */

import type { ExtensionContext, Theme } from "@earendil-works/pi-coding-agent";
import { getMarkdownTheme } from "@earendil-works/pi-coding-agent";
import {
  Key,
  Markdown,
  matchesKey,
  Text,
  truncateToWidth,
  visibleWidth,
} from "@earendil-works/pi-tui";
import { getFinalOutput } from "../subagent/format";
import { formatUsageStats, styleMultiline } from "../subagent/render";
import { schemaSummary } from "./render";
import type { WorkflowInputs } from "./runtime";
import type {
  WorkflowAgentRunSnapshot,
  WorkflowRunSnapshot,
} from "./status-registry";
import { getWorkflow, subscribeToWorkflows } from "./status-registry";

function formatElapsed(startedAt: number): string {
  const seconds = Math.round((Date.now() - startedAt) / 1000);
  return seconds < 60
    ? `${seconds}s`
    : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function statusIcon(
  theme: Theme,
  status: WorkflowAgentRunSnapshot["status"],
): string {
  if (status === "running") return theme.fg("accent", "◌");
  if (status === "error") return theme.fg("error", "✗");
  return theme.fg("success", "✓");
}

function phaseAgents(
  workflow: WorkflowRunSnapshot,
  phase: string,
): WorkflowAgentRunSnapshot[] {
  return workflow.agents.filter(
    (agent) => (agent.phase ?? "(no phase)") === phase,
  );
}

function phaseLine(
  theme: Theme,
  workflow: WorkflowRunSnapshot,
  title: string,
  selected: boolean,
  focused: boolean,
): string {
  const agents = phaseAgents(workflow, title);
  const done = agents.filter((agent) => agent.status !== "running").length;
  const hasError = agents.some((agent) => agent.status === "error");
  const isRunning = agents.some((agent) => agent.status === "running");
  const icon = hasError
    ? theme.fg("error", "✗")
    : isRunning
      ? theme.fg("accent", "◌")
      : agents.length > 0
        ? theme.fg("success", "✓")
        : theme.fg("muted", "○");
  const progress = agents.length > 0 ? ` ${done}/${agents.length}` : " waiting";
  const line = `${selected ? "▶ " : "  "}${icon} ${title}${theme.fg("dim", progress)}`;
  if (selected && focused)
    return theme.bg("selectedBg", theme.fg("accent", line));
  return selected ? theme.fg("accent", line) : theme.fg("muted", line);
}

function padLine(line: string, width: number): string {
  const clipped = truncateToWidth(line, width);
  return `${clipped}${" ".repeat(Math.max(0, width - visibleWidth(clipped)))}`;
}

function box(
  lines: string[],
  width: number,
  border: (value: string) => string,
): string[] {
  const innerWidth = Math.max(1, width - 4);
  const side = border("│");
  return [
    border(`╭${"─".repeat(Math.max(0, width - 2))}╮`),
    ...lines.map((line) => `${side} ${padLine(line, innerWidth)} ${side}`),
    border(`╰${"─".repeat(Math.max(0, width - 2))}╯`),
  ];
}

export function clampScroll(
  offset: number,
  contentRows: number,
  viewportRows: number,
): number {
  return Math.max(0, Math.min(offset, Math.max(0, contentRows - viewportRows)));
}

export function viewportLines(
  lines: string[],
  offset: number,
  rows: number,
): string[] {
  return lines.slice(
    clampScroll(offset, lines.length, rows),
    clampScroll(offset, lines.length, rows) + rows,
  );
}

/** Rows available inside a 70%-height overlay after its box chrome. */
export function overlayBodyRows(terminalRows: number): number {
  // `maxHeight: "70%"` applies after rendering; rendering more than this
  // clips the bottom border and keyboard hint. Reserve top/bottom borders,
  // title, divider, help, and one row of rounding/margin slack.
  return Math.max(1, Math.floor(terminalRows * 0.7) - 6);
}

function formatInputs(inputs: WorkflowInputs | undefined): string {
  if (!inputs) return "—";
  return Array.isArray(inputs)
    ? inputs.join(", ")
    : Object.entries(inputs)
        .map(([name, value]) => `${name}: ${value}`)
        .join("; ");
}

function inputArtifactNames(inputs: WorkflowInputs | undefined): string[] {
  if (!inputs) return [];
  return Array.isArray(inputs)
    ? inputs
    : [...Object.keys(inputs), ...Object.values(inputs)];
}

function usedLaterBy(
  workflow: WorkflowRunSnapshot,
  agent: WorkflowAgentRunSnapshot,
): string {
  const produces = agent.produces;
  if (!produces) return "—";
  const consumers = workflow.agents
    .filter((candidate) => candidate.id > agent.id)
    .filter((candidate) =>
      inputArtifactNames(candidate.inputs).includes(produces),
    )
    .map((candidate) => candidate.label);
  const phaseConsumers = workflow.phases
    .slice(workflow.phases.indexOf(agent.phase ?? "") + 1)
    .filter((phase) =>
      workflow.phaseMetadata?.[phase]?.inputs?.includes(produces),
    );
  return [...new Set([...consumers, ...phaseConsumers])].join(", ") || "—";
}

function detailLines(
  theme: Theme,
  workflow: WorkflowRunSnapshot,
  agent: WorkflowAgentRunSnapshot | undefined,
  width: number,
): string[] {
  if (!agent)
    return [theme.fg("muted", "No agents have started in this phase yet.")];

  const usage = agent.usage
    ? formatUsageStats(agent.usage, agent.model)
    : agent.model;
  const usedBy = usedLaterBy(workflow, agent);
  const metadata = [
    usage ? theme.fg("dim", usage) : "",
    agent.objective ? theme.fg("muted", `Objective: ${agent.objective}`) : "",
    agent.inputs
      ? theme.fg("muted", `Inputs: ${formatInputs(agent.inputs)}`)
      : "",
    agent.produces ? theme.fg("muted", `Produces: ${agent.produces}`) : "",
    usedBy !== "—" ? theme.fg("muted", `Used later by: ${usedBy}`) : "",
    agent.schema
      ? theme.fg("muted", `Output: ${schemaSummary(agent.schema)}`)
      : "",
    agent.objective ? "" : theme.fg("muted", "─── Task ───"),
  ];
  const task = agent.objective
    ? []
    : new Text(styleMultiline(theme, "dim", agent.task), 0, 0).render(width);
  const output = agent.errorMessage
    ? new Text(styleMultiline(theme, "error", agent.errorMessage), 0, 0).render(
        width,
      )
    : (() => {
        const text = agent.messages ? getFinalOutput(agent.messages) : "";
        return text
          ? new Markdown(text.trim(), 0, 0, getMarkdownTheme()).render(width)
          : [theme.fg("muted", "(waiting for output)")];
      })();
  return [
    ...metadata,
    ...task,
    theme.fg("muted", "─── Live output ───"),
    ...output,
  ].filter(Boolean);
}

function selectedAgentIndex(agents: WorkflowAgentRunSnapshot[]): number {
  const running = agents.findIndex((agent) => agent.status === "running");
  if (running >= 0) return running;
  const failed = agents.findIndex((agent) => agent.status === "error");
  return failed >= 0 ? failed : Math.max(0, agents.length - 1);
}

export async function showWorkflowStatusOverlay(
  ctx: ExtensionContext,
  workflowId: string,
): Promise<void> {
  await ctx.ui.custom<void>(
    (tui, theme, _keybindings, done) => {
      let phaseIndex = 0;
      let agentIndex = 0;
      let focusedPane: "phases" | "agents" = "phases";
      let previousPhase: string | undefined;
      let detailMode = false;
      let scrollOffset = 0;
      const unsubscribe = subscribeToWorkflows(() => {
        if (!getWorkflow(workflowId)) done();
        else tui.requestRender();
      });
      const timer = setInterval(() => tui.requestRender(), 1000);

      return {
        invalidate() {},
        dispose: () => {
          clearInterval(timer);
          unsubscribe();
        },
        render(width: number): string[] {
          const workflow = getWorkflow(workflowId);
          if (!workflow) return [];
          const phases =
            workflow.phases.length > 0 ? workflow.phases : ["(no phase)"];
          phaseIndex = Math.min(phaseIndex, phases.length - 1);
          const phase = phases[phaseIndex];
          const agents = phaseAgents(workflow, phase);
          if (phase !== previousPhase) {
            agentIndex = selectedAgentIndex(agents);
            previousPhase = phase;
          }
          agentIndex = Math.max(
            0,
            Math.min(agentIndex, Math.max(0, agents.length - 1)),
          );

          const innerWidth = Math.max(1, width - 4);
          const sidebarWidth = Math.min(
            30,
            Math.max(18, Math.floor(innerWidth * 0.3)),
          );
          const contentWidth = Math.max(1, innerWidth - sidebarWidth - 3);
          const phaseMetadata = workflow.phaseMetadata?.[phase];
          const sidebar = [
            theme.fg("muted", "Phases"),
            ...phases.map((title, index) =>
              phaseLine(
                theme,
                workflow,
                title,
                index === phaseIndex,
                focusedPane === "phases",
              ),
            ),
          ];
          const selected = agents[agentIndex];
          const content = [
            theme.fg("muted", `${phase} · ${agents.length} agents`),
            ...(phaseMetadata?.goal
              ? [theme.fg("dim", phaseMetadata.goal)]
              : []),
            ...agents.map((agent, index) => {
              const line = `${index === agentIndex ? "▶ " : "  "}${statusIcon(theme, agent.status)} ${agent.label} ${theme.fg("dim", `(${agent.agent})`)}`;
              if (index === agentIndex && focusedPane === "agents")
                return theme.bg("selectedBg", theme.fg("accent", line));
              return index === agentIndex ? theme.fg("accent", line) : line;
            }),
            "",
            ...detailLines(theme, workflow, selected, contentWidth),
          ];
          const detail = detailLines(theme, workflow, selected, innerWidth);
          const terminalRows = tui.terminal.rows;
          const bodyRows = overlayBodyRows(terminalRows);
          if (detailMode) {
            const visible = viewportLines(detail, scrollOffset, bodyRows);
            return box(
              [
                theme.fg(
                  "accent",
                  theme.bold(`${selected?.label ?? "Agent"} · ${phase}`),
                ),
                theme.fg("muted", "─".repeat(innerWidth)),
                ...visible,
                theme.fg(
                  "dim",
                  `↑/↓ scroll · PgUp/PgDn/Home/End · esc back (${scrollOffset + 1}-${Math.min(detail.length, scrollOffset + bodyRows)}/${detail.length})`,
                ),
              ],
              width,
              (value) => theme.fg("accent", value),
            );
          }
          const rows = Math.max(sidebar.length, content.length);
          const columns = Array.from({ length: rows }, (_, index) => {
            const left = sidebar[index] ?? "";
            const right = content[index] ?? "";
            return `${padLine(left, sidebarWidth)} ${theme.fg("muted", "│")} ${right}`;
          });
          const visible = viewportLines(columns, scrollOffset, bodyRows);
          return box(
            [
              theme.fg(
                "accent",
                theme.bold(
                  `Workflow ${workflow.name ?? workflow.workflowId} · ${formatElapsed(workflow.startedAt)} · ${workflow.tokensSpent} tok`,
                ),
              ),
              theme.fg("muted", "─".repeat(innerWidth)),
              ...visible,
              theme.fg(
                "dim",
                `←/→ pane · ↑/↓ select · enter full detail · pgup/pgdn scroll · esc close (${scrollOffset + 1}-${Math.min(rows, scrollOffset + bodyRows)}/${rows})`,
              ),
            ],
            width,
            (value) => theme.fg("accent", value),
          );
        },
        handleInput(data: string): void {
          const workflow = getWorkflow(workflowId);
          if (!workflow) return;
          const phases =
            workflow.phases.length > 0 ? workflow.phases : ["(no phase)"];
          const agents = phaseAgents(workflow, phases[phaseIndex]);
          const page = overlayBodyRows(tui.terminal.rows);
          if (detailMode) {
            const selected = agents[agentIndex];
            const lines = detailLines(
              theme,
              workflow,
              selected,
              Math.max(1, 60),
            );
            if (matchesKey(data, Key.escape)) {
              detailMode = false;
              scrollOffset = 0;
            } else if (matchesKey(data, Key.up)) scrollOffset--;
            else if (matchesKey(data, Key.down)) scrollOffset++;
            else if (matchesKey(data, Key.pageUp)) scrollOffset -= page;
            else if (matchesKey(data, Key.pageDown)) scrollOffset += page;
            else if (matchesKey(data, Key.home)) scrollOffset = 0;
            else if (matchesKey(data, Key.end)) scrollOffset = lines.length;
            scrollOffset = clampScroll(scrollOffset, lines.length, page);
            tui.requestRender();
            return;
          }
          if (matchesKey(data, Key.left)) {
            focusedPane = "phases";
          } else if (matchesKey(data, Key.right)) {
            focusedPane = "agents";
          } else if (matchesKey(data, Key.up)) {
            if (focusedPane === "phases") {
              phaseIndex = Math.max(0, phaseIndex - 1);
            } else {
              agentIndex = Math.max(0, agentIndex - 1);
            }
          } else if (matchesKey(data, Key.down)) {
            if (focusedPane === "phases") {
              phaseIndex = Math.min(phases.length - 1, phaseIndex + 1);
            } else {
              agentIndex = Math.min(
                Math.max(0, agents.length - 1),
                agentIndex + 1,
              );
            }
          } else if (matchesKey(data, Key.pageUp)) {
            scrollOffset = Math.max(0, scrollOffset - page);
          } else if (matchesKey(data, Key.pageDown)) {
            scrollOffset += page;
          } else if (matchesKey(data, Key.home)) {
            scrollOffset = 0;
          } else if (matchesKey(data, Key.end)) {
            scrollOffset = Number.MAX_SAFE_INTEGER;
          } else if (matchesKey(data, Key.enter)) {
            detailMode = true;
            scrollOffset = 0;
          } else if (matchesKey(data, Key.escape)) {
            done();
            return;
          }
          tui.requestRender();
        },
      };
    },
    {
      overlay: true,
      overlayOptions: {
        anchor: "bottom-center",
        width: "70%",
        minWidth: 50,
        maxHeight: "70%",
        margin: 1,
      },
    },
  );
}
