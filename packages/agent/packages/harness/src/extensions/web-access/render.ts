/**
 * Custom `renderCall` for `web_search`/`web_fetch` so the tool call header
 * shows the query/URL being requested instead of a bare `web_search` /
 * `web_fetch` label.
 */

import type { Theme } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";

const MAX_PREVIEW_LENGTH = 80;

/** Maximum lines shown in a collapsed web tool result before truncating. */
const COLLAPSED_PREVIEW_LINES = 15;

function truncate(text: string, max = MAX_PREVIEW_LENGTH): string {
  return text.length > max ? `${text.slice(0, max - 1)}\u2026` : text;
}

export function renderWebSearchCall(
  args: { query?: string; search_context_size?: string },
  theme: Theme,
): InstanceType<typeof Text> {
  const query = args?.query;
  let text = theme.fg("toolTitle", theme.bold("web_search"));
  text += query
    ? ` ${theme.fg("accent", truncate(query))}`
    : ` ${theme.fg("muted", "...")}`;
  if (args?.search_context_size) {
    text += theme.fg("dim", ` (${args.search_context_size})`);
  }
  return new Text(text, 0, 0);
}

export function renderWebFetchCall(
  args: { url?: string; prompt?: string },
  theme: Theme,
): InstanceType<typeof Text> {
  const url = args?.url;
  let text = theme.fg("toolTitle", theme.bold("web_fetch"));
  text += url
    ? ` ${theme.fg("accent", truncate(url))}`
    : ` ${theme.fg("muted", "...")}`;
  if (args?.prompt) {
    text += `\n  ${theme.fg("dim", truncate(args.prompt))}`;
  }
  return new Text(text, 0, 0);
}

interface RenderableResult {
  content: Array<{ type: string; text?: string }>;
}

function resultText(result: RenderableResult): string {
  return result.content
    .filter((c) => c.type === "text")
    .map((c) => c.text ?? "")
    .join("\n")
    .trim();
}

/**
 * Render a web tool result: a head-truncated preview when collapsed, the full
 * text when expanded. Errors are always shown in full (matches the built-in
 * `read`/`grep` tools). Without a `renderResult`, pi dumps the entire result
 * body unconditionally — this keeps large search/fetch payloads collapsible.
 */
export function renderWebResult(
  result: RenderableResult,
  options: { expanded: boolean; isPartial: boolean },
  theme: Theme,
  isError: boolean,
  partialLabel: string,
): InstanceType<typeof Text> {
  if (options.isPartial && !isError) {
    return new Text(theme.fg("warning", partialLabel), 0, 0);
  }

  const output = resultText(result);
  if (!output) {
    return new Text(theme.fg("dim", "No output"), 0, 0);
  }

  const lines = output.split("\n");

  // Errors and expanded results show everything.
  if (options.expanded || isError) {
    return new Text(
      `\n${lines.map((l) => theme.fg("toolOutput", l)).join("\n")}`,
      0,
      0,
    );
  }

  const display = lines.slice(0, COLLAPSED_PREVIEW_LINES);
  const remaining = lines.length - display.length;
  let text = `\n${display.map((l) => theme.fg("toolOutput", l)).join("\n")}`;
  if (remaining > 0) {
    text += `\n${theme.fg("muted", `… ${remaining} more lines (expand to see all)`)}`;
  }
  return new Text(text, 0, 0);
}

export function renderWebSearchResult(
  result: RenderableResult,
  options: { expanded: boolean; isPartial: boolean },
  theme: Theme,
  isError: boolean,
): InstanceType<typeof Text> {
  return renderWebResult(result, options, theme, isError, "Searching...");
}

export function renderWebFetchResult(
  result: RenderableResult,
  options: { expanded: boolean; isPartial: boolean },
  theme: Theme,
  isError: boolean,
): InstanceType<typeof Text> {
  return renderWebResult(result, options, theme, isError, "Fetching...");
}
