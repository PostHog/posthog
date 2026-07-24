import type { SignalReportStatus } from "@posthog/shared/types";

const MAX_HEADLINE_LENGTH = 140;

// Matches the first sentence terminator (. ! ?) optionally followed by closing
// Markdown emphasis markers (* _ `), before whitespace or end of input. Capture
// group 1 keeps the terminator so we don't lose it, but trailing emphasis is
// dropped at the boundary.
const SENTENCE_END = /([.!?])[*_`]*(?=\s|$)/;

const EDGE_EMPHASIS = /^[*_`\s]+|[*_`\s]+$/g;

/**
 * Compact single-sentence headline derived from a report summary, for list
 * rendering. Cuts at the first newline, then at the first sentence terminator,
 * strips edge Markdown emphasis, and truncates to ~140 chars with an ellipsis.
 *
 * Returns null for empty / non-string input so callers can fall back to the
 * full summary or a placeholder.
 */
export function deriveHeadline(
  summary: string | null | undefined,
): string | null {
  if (typeof summary !== "string") return null;
  const trimmed = summary.trim();
  if (!trimmed) return null;

  const firstLine = trimmed.split(/\r?\n/, 1)[0] ?? "";

  let headline = firstLine;
  const sentenceMatch = SENTENCE_END.exec(firstLine);
  if (sentenceMatch) {
    headline = firstLine.slice(
      0,
      sentenceMatch.index + sentenceMatch[1].length,
    );
  }

  headline = headline.replace(EDGE_EMPHASIS, "").trim();
  if (!headline) return null;

  if (headline.length > MAX_HEADLINE_LENGTH) {
    headline = `${headline.slice(0, MAX_HEADLINE_LENGTH).trimEnd()}…`;
  }

  return headline;
}

export function inboxStatusLabel(status: SignalReportStatus): string {
  switch (status) {
    case "ready":
      return "Ready";
    case "resolved":
      return "Resolved";
    case "pending_input":
      return "Needs input";
    case "in_progress":
      return "Researching";
    case "candidate":
      return "Queued";
    case "potential":
      return "Gathering";
    case "failed":
      return "Failed";
    case "suppressed":
      return "Suppressed";
    case "deleted":
      return "Deleted";
    default:
      return status;
  }
}

export function inboxStatusAccentCss(status: SignalReportStatus): string {
  switch (status) {
    case "ready":
      return "var(--green-9)";
    case "resolved":
      return "var(--green-9)";
    case "pending_input":
      return "var(--violet-9)";
    case "in_progress":
      return "var(--amber-9)";
    case "candidate":
      return "var(--cyan-9)";
    case "potential":
      return "var(--gray-9)";
    case "failed":
      return "var(--red-9)";
    default:
      return "var(--gray-8)";
  }
}

const SIGNAL_SUMMARY_SECTION_HEADERS = [
  "What's happening",
  "Root cause",
  "How to resolve",
] as const;

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Inserts line breaks around signal report summary section headers so each
 * label and its body render on separate lines (matches agent output like
 * `**What's happening:** text`).
 */
export function formatSignalReportSummaryMarkdown(content: string): string {
  let result = content;

  for (const header of SIGNAL_SUMMARY_SECTION_HEADERS) {
    const escaped = escapeRegExp(header);
    const boldHeaderPattern = `\\*\\*${escaped}:\\*\\*`;

    result = result.replace(
      new RegExp(`([^\\n])\\s*(${boldHeaderPattern})`, "gi"),
      "$1\n\n$2",
    );

    result = result.replace(
      new RegExp(`(${boldHeaderPattern})\\s+`, "gi"),
      "$1\n\n",
    );
  }

  return result;
}

/** Matches `type(scope): description` and optional breaking-change `!`. */
const CONVENTIONAL_COMMIT_TITLE = /^(\w+)(?:\(([^)]*)\))?!?:\s*(.+)$/;

export interface ParsedConventionalCommitTitle {
  type: string;
  scope: string | null;
  description: string;
}

export function parseConventionalCommitTitle(
  title: string | null | undefined,
): ParsedConventionalCommitTitle | null {
  if (typeof title !== "string") return null;

  const trimmed = title.trim();
  if (!trimmed) return null;

  const match = CONVENTIONAL_COMMIT_TITLE.exec(trimmed);
  if (!match) return null;

  const type = match[1].toLowerCase();
  const scopeRaw = match[2]?.trim();
  const description = match[3].trim();

  if (!description) return null;

  return {
    type,
    scope: scopeRaw ? scopeRaw : null,
    description,
  };
}

export function displayConventionalCommitTitle(
  title: string | null | undefined,
  fallback: string,
): string {
  const parsed = parseConventionalCommitTitle(title);
  if (parsed) return parsed.description;
  const trimmed = title?.trim();
  return trimmed ? trimmed : fallback;
}

export interface ParsedPrUrl {
  owner: string;
  repo: string;
  number: string;
  repoSlug: string;
}

export function parsePrUrl(prUrl: string): ParsedPrUrl | null {
  try {
    const url = new URL(prUrl);
    const match = url.pathname.match(
      /^\/([^/]+)\/([^/]+)\/pull\/(\d+)(?:$|[/?#])/,
    );
    if (!match) return null;
    const [, owner, repo, number] = match;
    return { owner, repo, number, repoSlug: `${owner}/${repo}` };
  } catch {
    return null;
  }
}
