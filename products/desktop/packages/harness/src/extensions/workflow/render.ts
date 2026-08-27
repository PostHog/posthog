/**
 * Custom `renderCall`/`renderResult` for the `workflow` tool: live
 * phase-grouped progress while the script runs, and a collapsed/expanded
 * (Ctrl+O) result view with per-agent result previews, workflow logs, token
 * spend, and the final synthesized result. Purely presentational over the
 * `WorkflowSnapshot` built in `extension.ts`.
 */
import type {
  AgentToolResult,
  Theme,
  ToolRenderResultOptions,
} from "@earendil-works/pi-coding-agent";
import {
  type Component,
  Container,
  Spacer,
  Text,
  truncateToWidth,
} from "@earendil-works/pi-tui";
import {
  extractWorkflowName,
  type WorkflowInputs,
  type WorkflowPhaseMetadata,
} from "./runtime";

/** Belt-and-suspenders: guarantee every rendered line fits `width`, regardless of what nested components did. */
function widthSafe(component: Component): Component {
  return {
    render: (width: number) =>
      component.render(width).map((line) => truncateToWidth(line, width)),
    invalidate: () => component.invalidate(),
  };
}

export interface WorkflowAgentStatus {
  id: number;
  label: string;
  agent: string;
  phase?: string;
  objective?: string;
  inputs?: WorkflowInputs;
  produces?: string;
  schema?: Record<string, unknown>;
  status: "running" | "done" | "error";
  resultPreview?: string;
}

export interface WorkflowSnapshot {
  name?: string;
  phases: string[];
  phaseMetadata?: Record<string, WorkflowPhaseMetadata>;
  currentPhase?: string;
  agents: WorkflowAgentStatus[];
  logs: string[];
  done: boolean;
  tokensSpent?: number;
  result?: unknown;
}

const COLLAPSED_MAX_AGENTS = 6;
const PREVIEW_CHARS = 70;

// Same frames/interval as pi-tui's own `Loader` (the app's global
// "working..." spinner) — not reused directly, since `Loader` owns a timer
// and needs a live `TUI` instance neither `renderCall` nor `renderResult`
// receive. Instead we just pick a frame from wall-clock time: while this
// tool call is running, pi's own working-status indicator is already calling
// `ui.requestRender()` on this exact cadence, so a plain time-based frame
// here rides that existing repaint loop and animates for free.
const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const SPINNER_INTERVAL_MS = 80;

function spinnerFrame(): string {
  const index =
    Math.floor(Date.now() / SPINNER_INTERVAL_MS) % SPINNER_FRAMES.length;
  return SPINNER_FRAMES[index];
}

export function previewOf(value: unknown): string | undefined {
  if (value === null || value === undefined) return undefined;
  const text =
    typeof value === "string" ? value : (safeJsonStringify(value) ?? "");
  const firstLine = text.trim().split("\n")[0] ?? "";
  if (!firstLine) return undefined;
  return firstLine.length > PREVIEW_CHARS
    ? `${firstLine.slice(0, PREVIEW_CHARS)}…`
    : firstLine;
}

export function schemaSummary(
  schema: Record<string, unknown> | undefined,
): string | undefined {
  if (!schema) return undefined;
  const type = typeof schema.type === "string" ? schema.type : "value";
  const required = Array.isArray(schema.required)
    ? schema.required.filter((key): key is string => typeof key === "string")
    : [];
  if (required.length === 0) return type;
  const visible = required.slice(0, 3);
  const remainder = required.length - visible.length;
  return `${type}; required: ${visible.join(", ")}${remainder > 0 ? ` +${remainder}` : ""}`;
}

/** Compact artifact → producing agent provenance for completed workflows. */
export function artifactProvenance(snapshot: WorkflowSnapshot): string[] {
  const agentArtifacts = snapshot.agents.flatMap((agent) =>
    agent.produces
      ? [
          `${agent.produces} ← ${agent.label}${agent.phase ? ` (${agent.phase})` : ""}`,
        ]
      : [],
  );
  const phaseArtifacts = snapshot.phases.flatMap((phase) =>
    (snapshot.phaseMetadata?.[phase]?.produces ?? []).map(
      (artifact) => `${artifact} ← ${phase}`,
    ),
  );
  return [...new Set([...agentArtifacts, ...phaseArtifacts])];
}

function safeJsonStringify(value: unknown): string | undefined {
  try {
    return JSON.stringify(value);
  } catch {
    return undefined;
  }
}

function formatTokens(count: number): string {
  if (count < 1000) return count.toString();
  if (count < 1_000_000) return `${Math.round(count / 1000)}k`;
  return `${(count / 1_000_000).toFixed(1)}M`;
}

function agentIcon(
  theme: Theme,
  status: WorkflowAgentStatus["status"],
): string {
  if (status === "running") return theme.fg("accent", spinnerFrame());
  if (status === "error") return theme.fg("error", "\u2717");
  return theme.fg("success", "\u2713");
}

interface PhaseGroup {
  title?: string;
  agents: WorkflowAgentStatus[];
}

/** Groups agents by phase, preserving first-seen phase order; phaseless agents lead. */
export function groupByPhase(agents: WorkflowAgentStatus[]): PhaseGroup[] {
  const groups: PhaseGroup[] = [];
  const byTitle = new Map<string | undefined, PhaseGroup>();
  for (const agent of agents) {
    let group = byTitle.get(agent.phase);
    if (!group) {
      group = { title: agent.phase, agents: [] };
      byTitle.set(agent.phase, group);
      groups.push(group);
    }
    group.agents.push(agent);
  }
  return groups;
}

function phaseHeader(theme: Theme, group: PhaseGroup): string {
  const done = group.agents.filter((a) => a.status !== "running").length;
  const total = group.agents.length;
  const allDone = done === total;
  const anyError = group.agents.some((a) => a.status === "error");
  const icon = allDone
    ? anyError
      ? theme.fg("error", "\u2717")
      : theme.fg("success", "\u2713")
    : theme.fg("accent", spinnerFrame());
  return `${icon} ${theme.fg("muted", group.title ?? "(no phase)")} ${theme.fg("dim", `${done}/${total}`)}`;
}

function agentLine(
  theme: Theme,
  agent: WorkflowAgentStatus,
  withPreview: boolean,
): string {
  let line = `  ${agentIcon(theme, agent.status)} ${theme.fg("accent", agent.label)} ${theme.fg("dim", `(${agent.agent})`)}`;
  if (withPreview && agent.resultPreview)
    line += `\n    ${theme.fg("toolOutput", agent.resultPreview)}`;
  return line;
}

export function renderWorkflowCall(
  args: { script?: string },
  theme: Theme,
): Component {
  const name = args.script ? extractWorkflowName(args.script) : undefined;
  return widthSafe(
    new Text(
      theme.fg("toolTitle", theme.bold("workflow")) +
        (name ? ` ${theme.fg("accent", name)}` : ""),
      0,
      0,
    ),
  );
}

// Deliberately does NOT repeat the current phase name here: the phase-group
// headers rendered directly below already show exactly which phase is in
// progress (via the spinner icon) versus done (✓) — restating it on this
// line too just duplicated the same fact twice for no new information.
function statusLine(theme: Theme, snapshot: WorkflowSnapshot): string {
  const doneCount = snapshot.agents.filter(
    (a) => a.status !== "running",
  ).length;
  const parts: string[] = [`${doneCount}/${snapshot.agents.length} agents`];
  if (snapshot.tokensSpent)
    parts.push(`${formatTokens(snapshot.tokensSpent)} tok`);
  let text = theme.fg("toolTitle", theme.bold("workflow "));
  if (snapshot.name) text += `${theme.fg("accent", snapshot.name)} `;
  return text + theme.fg("accent", parts.join(" \u00b7 "));
}

export function renderWorkflowResult(
  result: AgentToolResult<WorkflowSnapshot>,
  options: ToolRenderResultOptions,
  theme: Theme,
): Component {
  const snapshot = result.details;
  const fallback = result.content[0];
  const fallbackText =
    fallback?.type === "text" ? fallback.text : "(no output)";
  if (!snapshot || snapshot.agents.length === 0)
    return widthSafe(new Text(fallbackText, 0, 0));

  if (!options.expanded) {
    let text = statusLine(theme, snapshot);
    // Most recent agents win the limited collapsed space; earlier phases
    // collapse to just their header line.
    const groups = groupByPhase(snapshot.agents);
    let remaining = COLLAPSED_MAX_AGENTS;
    const rendered: string[] = [];
    for (let i = groups.length - 1; i >= 0; i--) {
      const group = groups[i];
      const lines: string[] = [phaseHeader(theme, group)];
      if (remaining > 0) {
        const visible = group.agents.slice(-remaining);
        remaining -= visible.length;
        const hidden = group.agents.length - visible.length;
        if (hidden > 0) lines.push(theme.fg("muted", `  (+${hidden} more)`));
        for (const agent of visible) lines.push(agentLine(theme, agent, false));
      }
      rendered.unshift(lines.join("\n"));
    }
    text += `\n${rendered.join("\n")}`;
    // Tool expansion is a host-level shortcut and is not consistently
    // available while custom editor components own input. Always surface a
    // compact final outcome here instead of making completed workflows depend
    // on Ctrl+O to reveal their useful result.
    if (snapshot.done) {
      const outcome = previewOf(snapshot.result) ?? fallbackText;
      text += `\n${theme.fg("muted", "─── Result ───")}`;
      text += `\n${theme.fg("toolOutput", outcome)}`;
    }
    return widthSafe(new Text(text, 0, 0));
  }

  const container = new Container();
  container.addChild(new Text(statusLine(theme, snapshot), 0, 0));
  for (const group of groupByPhase(snapshot.agents)) {
    const lines = [phaseHeader(theme, group)];
    for (const agent of group.agents) lines.push(agentLine(theme, agent, true));
    container.addChild(new Text(lines.join("\n"), 0, 0));
  }
  if (snapshot.logs.length > 0) {
    container.addChild(new Spacer(1));
    container.addChild(
      new Text(
        theme.fg("muted", "\u2500\u2500\u2500 Logs \u2500\u2500\u2500"),
        0,
        0,
      ),
    );
    container.addChild(
      new Text(
        snapshot.logs.map((line) => theme.fg("dim", line)).join("\n"),
        0,
        0,
      ),
    );
  }
  if (snapshot.done && artifactProvenance(snapshot).length > 0) {
    container.addChild(new Spacer(1));
    container.addChild(new Text(theme.fg("muted", "─── Artifacts ───"), 0, 0));
    container.addChild(
      new Text(
        artifactProvenance(snapshot)
          .map((artifact) => theme.fg("dim", artifact))
          .join("\n"),
        0,
        0,
      ),
    );
  }
  if (snapshot.done) {
    container.addChild(new Spacer(1));
    container.addChild(
      new Text(
        theme.fg("muted", "\u2500\u2500\u2500 Result \u2500\u2500\u2500"),
        0,
        0,
      ),
    );
    container.addChild(new Text(theme.fg("toolOutput", fallbackText), 0, 0));
  }
  return widthSafe(container);
}
