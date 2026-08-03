/**
 * Custom `renderCall`/`renderResult` for the `subagent` tool: collapsed
 * (default) and expanded (Ctrl+O) completed-result views and per-run usage
 * stats. Live task state belongs in `status-overlay.ts`. Purely presentational over `format.ts`'s
 * pure data — no behavior change to any other module. Modes: `single` and
 * `parallel` only — there is no chain mode.
 */

import type {
  AgentToolResult,
  Theme,
  ToolRenderResultOptions,
} from "@earendil-works/pi-coding-agent";
import { getMarkdownTheme } from "@earendil-works/pi-coding-agent";
import {
  type Component,
  Container,
  Markdown,
  Spacer,
  Text,
  truncateToWidth,
} from "@earendil-works/pi-tui";
import { getFinalOutput } from "./format";
import {
  isFailedResult,
  type SingleRunResult,
  type UsageStats,
} from "./run-agent";

/** `theme.fg()` only resets its own escape at the *end* of the string it's given —
 * calling it once around text that already contains literal newlines leaves
 * that reset dangling past the first wrapped line, which can throw off the
 * TUI's width accounting on the following lines. Re-apply the color per line. */
export function styleMultiline(
  theme: Theme,
  color: Parameters<Theme["fg"]>[0],
  text: string,
): string {
  return text
    .split("\n")
    .map((line) => theme.fg(color, line))
    .join("\n");
}

/** Belt-and-suspenders: guarantee every rendered line fits `width`, regardless of what nested components did. */
function widthSafe(component: Component): Component {
  return {
    render: (width: number) =>
      component.render(width).map((line) => truncateToWidth(line, width)),
    invalidate: () => component.invalidate(),
  };
}

function formatTokens(count: number): string {
  if (count < 1000) return count.toString();
  if (count < 10_000) return `${(count / 1000).toFixed(1)}k`;
  if (count < 1_000_000) return `${Math.round(count / 1000)}k`;
  return `${(count / 1_000_000).toFixed(1)}M`;
}

function formatDuration(ms: number): string {
  const totalSeconds = Math.max(0, Math.round(ms / 1000));
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${seconds}s`;
}

/** e.g. `Done (48.9k tokens · 1m 16s)` / `Running... (12.3k tokens · 34s)`. */
function formatCompactStatus(theme: Theme, result: SingleRunResult): string {
  const elapsedMs = (result.endedAt ?? Date.now()) - result.startedAt;
  const tokens = result.usage.input + result.usage.output;
  const tokensPrefix = tokens > 0 ? `${formatTokens(tokens)} tokens · ` : "";
  const suffix = `(${tokensPrefix}${formatDuration(elapsedMs)})`;

  if (result.exitCode === -1) return theme.fg("dim", `Running... ${suffix}`);
  if (isFailedResult(result)) {
    const reason = result.errorMessage ? `: ${result.errorMessage}` : "";
    return theme.fg("error", `Failed${reason} ${suffix}`);
  }
  return theme.fg("success", `Done ${suffix}`);
}

export function formatUsageStats(usage: UsageStats, model?: string): string {
  const parts: string[] = [];
  if (usage.turns)
    parts.push(`${usage.turns} turn${usage.turns > 1 ? "s" : ""}`);
  if (usage.input) parts.push(`\u2191${formatTokens(usage.input)}`);
  if (usage.output) parts.push(`\u2193${formatTokens(usage.output)}`);
  if (usage.cacheRead) parts.push(`R${formatTokens(usage.cacheRead)}`);
  if (usage.cacheWrite) parts.push(`W${formatTokens(usage.cacheWrite)}`);
  if (usage.cost) parts.push(`$${usage.cost.toFixed(4)}`);
  if (usage.contextTokens > 0)
    parts.push(`ctx:${formatTokens(usage.contextTokens)}`);
  if (model) parts.push(model);
  return parts.join(" ");
}

function statusIcon(theme: Theme, result: SingleRunResult): string {
  if (result.exitCode === -1) return theme.fg("warning", "\u23f3");
  return isFailedResult(result)
    ? theme.fg("error", "\u2717")
    : theme.fg("success", "\u2713");
}

interface SubagentRenderDetails {
  mode: "single" | "parallel";
  results: SingleRunResult[];
}

function callLine(
  theme: Theme,
  agent: string,
  task: string,
  index: number | undefined,
): string {
  const preview = task.length > 60 ? `${task.slice(0, 60)}…` : task;
  const prefix = index !== undefined ? theme.fg("dim", `${index + 1}. `) : "";
  return `${prefix}${theme.fg("toolTitle", theme.bold(agent))}${theme.fg("dim", `(${preview})`)}`;
}

export function renderSubagentCall(
  args: {
    agent?: string;
    task?: string;
    tasks?: Array<{ agent: string; task: string }>;
  },
  theme: Theme,
): Component {
  if (args.tasks && args.tasks.length > 0) {
    const lines = args.tasks.map((t, i) => callLine(theme, t.agent, t.task, i));
    return widthSafe(new Text(lines.join("\n"), 0, 0));
  }

  return widthSafe(
    new Text(
      callLine(theme, args.agent ?? "...", args.task ?? "...", undefined),
      0,
      0,
    ),
  );
}

function renderSingle(
  result: SingleRunResult,
  theme: Theme,
  expanded: boolean,
) {
  const icon = statusIcon(theme, result);
  const finalOutput = getFinalOutput(result.messages);
  const usageStr = formatUsageStats(result.usage, result.model);

  if (!expanded) {
    // The call slot already names the agent (`Agent(task)`); don't repeat it here.
    return new Text(formatCompactStatus(theme, result), 0, 0);
  }

  const container = new Container();
  container.addChild(
    new Text(
      `${icon} ${theme.fg("toolTitle", theme.bold(result.agent))}`,
      0,
      0,
    ),
  );
  container.addChild(new Spacer(1));
  container.addChild(
    new Text(
      theme.fg("muted", "\u2500\u2500\u2500 Task \u2500\u2500\u2500"),
      0,
      0,
    ),
  );
  container.addChild(new Text(styleMultiline(theme, "dim", result.task), 0, 0));
  container.addChild(new Spacer(1));
  container.addChild(
    new Text(
      theme.fg("muted", "\u2500\u2500\u2500 Output \u2500\u2500\u2500"),
      0,
      0,
    ),
  );
  if (isFailedResult(result) && result.errorMessage) {
    container.addChild(
      new Text(styleMultiline(theme, "error", result.errorMessage), 0, 0),
    );
  } else if (finalOutput) {
    container.addChild(
      new Markdown(finalOutput.trim(), 0, 0, getMarkdownTheme()),
    );
  } else {
    container.addChild(new Text(theme.fg("muted", "(no output)"), 0, 0));
  }
  if (usageStr) {
    container.addChild(new Spacer(1));
    container.addChild(new Text(theme.fg("dim", usageStr), 0, 0));
  }
  return container;
}

export function renderSubagentResult(
  result: AgentToolResult<SubagentRenderDetails>,
  options: ToolRenderResultOptions,
  theme: Theme,
): Component {
  const details = result.details;

  if (!details || details.results.length === 0) {
    const text = result.content[0];
    return widthSafe(
      new Text(text?.type === "text" ? text.text : "(no output)", 0, 0),
    );
  }

  if (details.mode === "single") {
    return widthSafe(renderSingle(details.results[0], theme, options.expanded));
  }

  const label = "parallel";
  const successCount = details.results.filter(
    (r) => !isFailedResult(r) && r.exitCode !== -1,
  ).length;
  const running = details.results.filter((r) => r.exitCode === -1).length;
  const status =
    running > 0
      ? `${successCount}/${details.results.length} done, ${running} running`
      : `${successCount}/${details.results.length} succeeded`;

  if (!options.expanded) {
    // Positionally aligned with the call slot's numbered task list above —
    // don't repeat the agent name per row, matching pi's own convention of
    // stating parameters once in the call header rather than in every
    // result line (e.g. bash never repeats its command in its output).
    let text = `${theme.fg("toolTitle", theme.bold(`${label} `))}${theme.fg("accent", status)}`;
    for (const [i, r] of details.results.entries()) {
      text += `\n${theme.fg("dim", `${i + 1}. `)}${formatCompactStatus(theme, r)}`;
    }
    if (running === 0) {
      text += `\n${theme.fg("muted", "(Ctrl+O to expand)")}`;
    }
    return widthSafe(new Text(text, 0, 0));
  }

  const container = new Container();
  container.addChild(
    new Text(
      `${theme.fg("toolTitle", theme.bold(`${label} `))}${theme.fg("accent", status)}`,
      0,
      0,
    ),
  );
  for (const r of details.results) {
    container.addChild(new Spacer(1));
    container.addChild(renderSingle(r, theme, true));
  }
  return widthSafe(container);
}
