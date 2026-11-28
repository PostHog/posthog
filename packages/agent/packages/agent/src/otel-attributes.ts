import {
  readAgentToolName,
  readMcpToolDescriptor,
} from "@posthog/agent-contracts";
import {
  contextWikiPageKind,
  contextWikiRelativePath,
} from "@posthog/harness/extensions/context-wiki";

const MAX_BODY_CHARS = 2000;
// PostHog Logs only facets attribute key/value pairs shorter than 256 chars,
// so free-text attribute values are capped well below that.
const MAX_ATTR_CHARS = 200;
// The SDK default export timeout is 30s; a hanging endpoint must not hold up
// session cleanup (the sandbox can be torn down right after), so keep it short.
const EXPORT_TIMEOUT_MS = 5000;

// Batch flush cadence shared by the log and span processors.
const DEFAULT_FLUSH_INTERVAL_MS = 2000;

const HOOK_REJECTED_INPUT_TEXT =
  "returned updatedInput that failed schema validation";

export type ToolFailureReason =
  | "hook_rejected_input"
  | "permission_denied"
  | "tool_error";

export type AttributeValue = string | number | boolean;
export type Attributes = Record<string, AttributeValue>;

export { DEFAULT_FLUSH_INTERVAL_MS, EXPORT_TIMEOUT_MS, MAX_BODY_CHARS };

/**
 * extNotification() can double-prefix custom methods (see matchesExt in
 * acp-extensions.ts); normalize so both spellings map identically.
 */
export function normalizeMethod(method: string): string {
  return method.startsWith("__posthog/") ? method.slice(1) : method;
}

export function asString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

export function truncate(value: string, max: number): string {
  return value.length <= max ? value : `${value.slice(0, max)}…`;
}

export function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

export function toolNameAttribute(
  update: Record<string, unknown>,
): string | undefined {
  if (readMcpToolDescriptor(update._meta)) return "mcp";
  return readAgentToolName(update._meta) || undefined;
}

// Agents read pages with read and search tools and with shell commands; an edit is not a read.
const WIKI_READ_TOOL_KINDS = new Set(["read", "search", "execute"]);
const WIKI_PAGE_RETRIEVE_TOOL = /^(?:task-)?context-wiki-page-retrieve$/;
// The PostHog MCP `exec` tool takes `call [--flags] <tool> <json input>`.
const MCP_EXEC_CALL = /^\s*call\s+(?:--\S+\s+)*(\S+)\s*([\s\S]*)$/;
const SHELL_PATH_END = "[^\\s'\"`;|&<>()]+";

/**
 * Adds the context wiki pages a tool update names to `pages`, keyed by their
 * path relative to the mount, with the page's kind as the value. The paths stay
 * in the sandbox: page names are written by customers, so only the count and
 * the kinds are exported.
 */
export function collectContextWikiPages(
  update: Record<string, unknown>,
  toolKind: string,
  wikiPath: string | undefined,
  pages: Map<string, string>,
): void {
  const add = (relativePath: string | undefined): void => {
    const kind = relativePath && contextWikiPageKind(relativePath);
    if (relativePath && kind) pages.set(relativePath, kind);
  };
  add(mcpRetrievedPagePath(update));
  if (!wikiPath || !WIKI_READ_TOOL_KINDS.has(toolKind)) return;
  for (const location of Array.isArray(update.locations)
    ? update.locations
    : []) {
    const path = asString(asRecord(location)?.path);
    if (path) add(contextWikiRelativePath(path, wikiPath));
  }
  // A shell read carries no locations: Claude's Bash input holds the command,
  // and Codex puts the command in the title.
  const root = escapeRegExp(wikiPath.replace(/\/+$/, ""));
  const shellPath = new RegExp(`${root}/${SHELL_PATH_END}`, "g");
  for (const text of [
    asString(asRecord(update.rawInput)?.command),
    asString(update.title),
  ]) {
    for (const match of text?.match(shellPath) ?? []) {
      add(contextWikiRelativePath(match, wikiPath));
    }
  }
}

/** The page a context wiki retrieve tool asked for, called directly or through PostHog MCP `exec`. */
function mcpRetrievedPagePath(
  update: Record<string, unknown>,
): string | undefined {
  const mcp = readMcpToolDescriptor(update._meta);
  if (!mcp) return undefined;
  const input = asRecord(update.rawInput);
  if (WIKI_PAGE_RETRIEVE_TOOL.test(mcp.tool)) return asString(input?.path);
  if (mcp.tool !== "exec") return undefined;
  const call = MCP_EXEC_CALL.exec(asString(input?.command) ?? "");
  if (!call || !WIKI_PAGE_RETRIEVE_TOOL.test(call[1])) return undefined;
  try {
    return asString(asRecord(JSON.parse(call[2]))?.path);
  } catch {
    return undefined;
  }
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function contextWikiReadAttributes(
  pages: Map<string, string>,
): Attributes {
  if (!pages.size) return {};
  return {
    context_wiki_page_reads: pages.size,
    context_wiki_page_kinds: [...new Set(pages.values())].sort().join(","),
  };
}

export function toolFailureReason(
  update: Record<string, unknown>,
): ToolFailureReason {
  if (
    asRecord(asRecord(update._meta)?.claudeCode)?.failureReason ===
    "permission_denied"
  ) {
    return "permission_denied";
  }
  const content = Array.isArray(update.content) ? update.content : [];
  for (const entry of content) {
    const block = asRecord(entry);
    if (block?.type !== "content") continue;
    const inner = asRecord(block.content);
    const text = inner?.type === "text" ? asString(inner.text) : undefined;
    if (text?.includes(HOOK_REJECTED_INPUT_TEXT)) return "hook_rejected_input";
  }
  return "tool_error";
}

export function strAttr(
  attrs: Attributes,
  key: string,
  value: unknown,
  max = MAX_ATTR_CHARS,
): string | undefined {
  if (typeof value !== "string" || value.length === 0) return undefined;
  const truncated = truncate(value, max);
  attrs[key] = truncated;
  return truncated;
}

export function numAttr(attrs: Attributes, key: string, value: unknown): void {
  if (typeof value === "number" && Number.isFinite(value)) {
    attrs[key] = value;
  }
}

export function usageAttributes(params: Record<string, unknown>): Attributes {
  const attrs: Attributes = {};
  const used = asRecord(params.used);
  if (used) {
    numAttr(attrs, "tokens_input", used.inputTokens);
    numAttr(attrs, "tokens_output", used.outputTokens);
    numAttr(attrs, "tokens_cached_read", used.cachedReadTokens);
    numAttr(attrs, "tokens_cached_write", used.cachedWriteTokens);
  }
  // Claude sends a plain number; other shapes carry { amount }.
  const cost =
    typeof params.cost === "number"
      ? params.cost
      : asRecord(params.cost)?.amount;
  numAttr(attrs, "cost_usd", cost);
  return attrs;
}

/** Timestamp of a stored entry as a Date, falling back to now when invalid. */
export function entryTime(timestamp: string): Date {
  const parsed = new Date(timestamp);
  return Number.isNaN(parsed.getTime()) ? new Date() : parsed;
}
