import type {
  SignalReportActionability,
  SignalReportStatus,
} from "@posthog/shared/types";

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

/**
 * Whether the status badge should be hidden because the actionability badge
 * already tells the same story: "ready" is the default terminal state (the
 * actionability verdict is the more specific fact), and "pending_input" next
 * to a requires_human_input verdict would render two identical "Needs input"
 * badges.
 */
export function isStatusRedundantWithActionability(
  status: SignalReportStatus,
  actionability: SignalReportActionability | null | undefined,
): boolean {
  if (!actionability) {
    return false;
  }
  return (
    status === "ready" ||
    (status === "pending_input" && actionability === "requires_human_input")
  );
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

/**
 * The human display title: conventional-commit prefixes stripped and the first
 * letter capitalized, so "fix(oauth): validate scopes" reads "Validate scopes".
 * Reports present as briefs, not commits — the commit-shaped title still lives
 * on the PR itself.
 */
export function humanizeReportTitle(
  title: string | null | undefined,
  fallback: string,
): string {
  const display = displayConventionalCommitTitle(title, fallback);
  return display.charAt(0).toUpperCase() + display.slice(1);
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
    // Only a real GitHub PR URL may drive "Open in GitHub" affordances —
    // implementation_pr_url flows in from task-run output, so an arbitrary
    // host here would let a task point reviewers at an attacker's site.
    if (url.protocol !== "https:" || url.hostname !== "github.com") {
      return null;
    }
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

export interface ReportSummarySplit {
  /** Prose before the first `##` heading — the summary's own tl;dr. */
  lede: string;
  /** The `##` sections, in document order, bodies untrimmed of markdown. */
  sections: { title: string; body: string }[];
}

/**
 * Split a report summary into its labeled slots: the tl;dr lede and each
 * `##` section (Problem, Impact, Solution, ...). The reader jumps to the slot
 * they need instead of reconstructing the structure by reading linearly —
 * nothing is cut, it's sorted. Summaries without `##` headings return an
 * empty section list, and callers render them whole.
 */
export function splitReportSummary(
  summary: string | null | undefined,
): ReportSummarySplit {
  if (typeof summary !== "string" || !summary.trim()) {
    return { lede: "", sections: [] };
  }
  const lines = summary.split(/\r?\n/);
  const sections: { title: string; body: string }[] = [];
  const lede: string[] = [];
  let current: { title: string; body: string[] } | null = null;
  for (const line of lines) {
    const heading = /^##\s+(.+?)\s*$/.exec(line);
    if (heading) {
      if (current) {
        sections.push({
          title: current.title,
          body: current.body.join("\n").trim(),
        });
      }
      current = { title: heading[1], body: [] };
    } else if (current) {
      current.body.push(line);
    } else {
      lede.push(line);
    }
  }
  if (current) {
    sections.push({
      title: current.title,
      body: current.body.join("\n").trim(),
    });
  }
  return { lede: lede.join("\n").trim(), sections };
}
