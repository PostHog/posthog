/**
 * Custom `renderCall`/`renderResult` for MCP tools.
 *
 *   - `renderMcpToolCall` — individual bridged MCP tools (`mcp_<server>_<tool>`).
 *     pi's fallback renderer shows only the tool name, which hides the
 *     arguments the model actually sent — exactly what you need to see when
 *     a call fails (wrong id, missing field). Collapsed: name + compact
 *     single-line JSON (truncated). Expanded: full pretty-printed arguments.
 *   - `renderMcpProxyCall`/`renderMcpProxyResult` — the `mcp` search/call
 *     proxy tool. Its `content` text is written for the model (flat,
 *     unstyled); these render the structured `details` instead so the TUI
 *     shows a real list/summary rather than a wall of text.
 */

import type {
  Theme,
  ToolRenderResultOptions,
} from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import type { Hit, McpProxyDetails } from "./proxy-tool";

const MAX_COLLAPSED_ARGS_LENGTH = 120;

/** Compact single-line JSON preview of tool arguments. Empty for no args. */
export function formatArgsCompact(
  args: unknown,
  maxLength = MAX_COLLAPSED_ARGS_LENGTH,
): string {
  if (args === undefined || args === null) return "";
  let json: string;
  try {
    json = JSON.stringify(args) ?? "";
  } catch {
    json = String(args);
  }
  if (json === "" || json === "{}") return "";
  return json.length > maxLength ? `${json.slice(0, maxLength - 1)}…` : json;
}

/** Full pretty-printed arguments for the expanded view. Empty for no args. */
export function formatArgsExpanded(args: unknown): string {
  if (args === undefined || args === null) return "";
  let json: string;
  try {
    json = JSON.stringify(args, null, 2) ?? "";
  } catch {
    json = String(args);
  }
  return json === "" || json === "{}" ? "" : json;
}

export function renderMcpToolCall(
  piName: string,
  args: unknown,
  theme: Theme,
  expanded: boolean,
): InstanceType<typeof Text> {
  let text = theme.fg("toolTitle", theme.bold(piName));
  if (expanded) {
    const pretty = formatArgsExpanded(args);
    if (pretty) {
      text += `\n${pretty
        .split("\n")
        .map((line) => theme.fg("dim", line))
        .join("\n")}`;
    }
  } else {
    const compact = formatArgsCompact(args);
    if (compact) text += ` ${theme.fg("muted", compact)}`;
  }
  return new Text(text, 0, 0);
}

/** Shape of the `mcp` proxy tool's call arguments, for `renderCall`. */
interface McpProxyArgs {
  search?: string;
  tool?: string;
  args?: string;
}

export function renderMcpProxyCall(
  args: McpProxyArgs,
  theme: Theme,
  expanded: boolean,
): InstanceType<typeof Text> {
  const label = theme.fg("toolTitle", theme.bold("mcp"));
  if (args?.search) {
    return new Text(
      `${label} ${theme.fg("muted", "search:")} ${theme.fg("dim", `"${args.search}"`)}`,
      0,
      0,
    );
  }
  if (args?.tool) {
    let text = `${label} ${theme.fg("muted", "\u2192")} ${theme.fg("dim", args.tool)}`;
    // `args.args` is already a JSON-encoded string (the proxy tool's flat
    // schema), not an object — format it directly rather than through
    // formatArgsCompact/Expanded, which would JSON.stringify (double-encode) it.
    if (expanded) {
      const pretty = formatJsonArgString(args.args, { pretty: true });
      if (pretty) {
        text += `\n${pretty
          .split("\n")
          .map((line) => theme.fg("dim", line))
          .join("\n")}`;
      }
    } else {
      const compact = formatJsonArgString(args.args, {
        pretty: false,
        maxLength: MAX_COLLAPSED_ARGS_LENGTH,
      });
      if (compact) text += ` ${theme.fg("muted", compact)}`;
    }
    return new Text(text, 0, 0);
  }
  return new Text(label, 0, 0);
}

/**
 * Format the `mcp` proxy tool's `args` string (already JSON-encoded) for
 * display: re-serialized compactly or pretty-printed, falling back to the
 * raw string if it isn't valid JSON.
 */
function formatJsonArgString(
  raw: string | undefined,
  options: { pretty: boolean; maxLength?: number },
): string {
  if (!raw || raw.trim() === "" || raw.trim() === "{}") return "";
  let text = raw;
  try {
    const parsed: unknown = JSON.parse(raw);
    text = options.pretty
      ? JSON.stringify(parsed, null, 2)
      : JSON.stringify(parsed);
  } catch {
    // Not valid JSON (e.g. a partial/streaming call) — show the raw string.
  }
  if (!options.maxLength || text.length <= options.maxLength) return text;
  return `${text.slice(0, options.maxLength - 1)}\u2026`;
}

const COLLAPSED_HIT_COUNT = 6;
const COLLAPSED_CALL_LINES = 6;
const COLLAPSED_CALL_CHARS = 1_000;

function formatHitLine(hit: Hit, theme: Theme): string {
  if (!hit.piName) {
    return `${theme.fg("dim", "\u25cb")} ${theme.bold(hit.serverName)} ${theme.fg("muted", "(server, not connected)")} \u2014 ${theme.fg("dim", hit.description)}`;
  }
  const marker = hit.connected
    ? theme.fg("success", "\u25cf")
    : theme.fg("dim", "\u25cb");
  const suffix = hit.connected
    ? ""
    : ` ${theme.fg("muted", "(not connected)")}`;
  return `${marker} ${theme.bold(hit.piName)}${suffix} \u2014 ${theme.fg("dim", hit.description)}`;
}

function renderSearchResult(
  query: string,
  hits: Hit[],
  theme: Theme,
  expanded: boolean,
): string {
  const header = theme.fg(
    "muted",
    `${hits.length} result${hits.length === 1 ? "" : "s"} for "${query}"`,
  );
  if (hits.length === 0) return header;
  const shown = expanded ? hits : hits.slice(0, COLLAPSED_HIT_COUNT);
  const lines = shown.map((hit) => formatHitLine(hit, theme));
  const hiddenCount = hits.length - shown.length;
  const footer =
    hiddenCount > 0
      ? [theme.fg("muted", `\u2026and ${hiddenCount} more — expand to see all`)]
      : [];
  return [header, ...lines, ...footer].join("\n");
}

function renderCallOutput(
  server: string,
  tool: string,
  content: ReadonlyArray<{ type: string; text?: string }>,
  theme: Theme,
  expanded: boolean,
): string {
  const header = `${theme.fg("toolTitle", theme.bold(server))} ${theme.fg("muted", "\u2192")} ${theme.fg("dim", tool)}`;
  const text = content
    .map((c) => (c.type === "text" ? (c.text ?? "") : `[${c.type}]`))
    .join("\n")
    .trim();
  if (!text) return header;

  if (expanded) {
    return `${header}\n${text
      .split("\n")
      .map((line) => theme.fg("dim", line))
      .join("\n")}`;
  }

  const lines = text.split("\n");
  const truncatedByLines = lines.length > COLLAPSED_CALL_LINES;
  let collapsed = lines.slice(0, COLLAPSED_CALL_LINES).join("\n");
  let truncated = truncatedByLines;
  if (collapsed.length > COLLAPSED_CALL_CHARS) {
    collapsed = collapsed.slice(0, COLLAPSED_CALL_CHARS);
    truncated = true;
  }
  const body = collapsed
    .split("\n")
    .map((line) => theme.fg("dim", line))
    .join("\n");
  const footer = truncated
    ? `\n${theme.fg("muted", "\u2026 output truncated — expand to see all")}`
    : "";
  return `${header}\n${body}${footer}`;
}

/** Result shape the `mcp` proxy tool actually returns (see proxy-tool.ts). */
interface McpProxyResult {
  content: ReadonlyArray<{ type: string; text?: string }>;
  details?: McpProxyDetails;
  isError?: boolean;
}

export function renderMcpProxyResult(
  result: McpProxyResult,
  options: ToolRenderResultOptions,
  theme: Theme,
): InstanceType<typeof Text> {
  const details = result.details;
  if (options.isPartial || !details) {
    const text = result.content
      .map((c) => (c.type === "text" ? (c.text ?? "") : `[${c.type}]`))
      .join("\n");
    return new Text(text, 0, 0);
  }

  switch (details.kind) {
    case "search":
      return new Text(
        renderSearchResult(
          details.query,
          details.hits,
          theme,
          options.expanded,
        ),
        0,
        0,
      );
    case "connect": {
      const text =
        details.toolCount > 0
          ? `${theme.fg("success", "\u2713")} connected to ${theme.bold(details.server)} \u2014 ${details.toolCount} tools (${theme.fg("muted", "search to find one")})`
          : `${theme.fg("warning", "\u25cb")} connected to ${theme.bold(details.server)} \u2014 no tools reported`;
      return new Text(text, 0, 0);
    }
    case "call":
      return new Text(
        renderCallOutput(
          details.server,
          details.tool,
          result.content,
          theme,
          options.expanded,
        ),
        0,
        0,
      );
    case "error":
      return new Text(theme.fg("error", details.message), 0, 0);
    case "no-config":
    case "usage":
      return new Text(
        theme.fg(
          "muted",
          result.content.find((c) => c.type === "text")?.text ?? "",
        ),
        0,
        0,
      );
    default:
      return new Text(
        result.content
          .map((c) => (c.type === "text" ? (c.text ?? "") : ""))
          .join("\n"),
        0,
        0,
      );
  }
}
