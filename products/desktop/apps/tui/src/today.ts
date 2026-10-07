import { visibleWidth } from "@earendil-works/pi-tui";
import { blue, orange } from "./theme";

// The day's briefing, as the Today API returns it. PostHog writes one each morning in the user's time zone.
export interface BriefingSegment {
  text: string;
  // The item this run of text links to, or null for plain text.
  item_key: string | null;
  highlight: boolean;
}

export interface BriefingItem {
  key: string;
  label: string;
  title: string;
  // A path on the PostHog web app, such as /project/2/inbox/<report id>.
  url: string;
  state: string;
}

export interface Briefing {
  status: "collecting" | "writing" | "ready" | "failed";
  headline: string;
  paragraphs: BriefingSegment[][];
  items: BriefingItem[];
  more_reports_count: number;
}

export type TodayState =
  | { kind: "loading" }
  | { kind: "ready"; briefing: Briefing; firstName: string | null }
  | { kind: "error"; reason: "unavailable" | "signIn" | "failed" };

// What a click on the briefing does.
export type TodayAction =
  | { kind: "item"; item: BriefingItem }
  | { kind: "inbox" }
  | { kind: "ask" };

export interface TodayHit {
  row: number;
  start: number;
  end: number;
  action: TodayAction;
}

export const WALKTHROUGH_PROMPT =
  "Walk me through what changed in my product today.";

// The questions the web app offers for a report that suggests none of its own.
export const DEFAULT_REPORT_QUESTIONS = [
  "Why is this happening?",
  "Who is affected, and how badly?",
  "What would you look at first?",
];

// A report's chat names the report, so the agent can read it with its PostHog tools.
export function reportPrompt(
  question: string,
  item: BriefingItem,
  webUrl: string,
): string {
  return `${question}\n\nThis is about the Inbox report "${item.title}": ${webUrl}`;
}

export function greeting(hour: number, firstName: string | null): string {
  const time =
    hour < 5
      ? "You're up late"
      : hour < 12
        ? "Morning"
        : hour < 17
          ? "Afternoon"
          : "Evening";
  return firstName ? `${time}, ${firstName}.` : `${time}.`;
}

interface Run {
  text: string;
  style: (text: string) => string;
  action?: TodayAction;
}

const plain = (text: string): string => text;
const bold = (text: string): string => `\u001b[1m${text}\u001b[22m`;
const dim = (text: string): string => `\u001b[2m${text}\u001b[22m`;
const underline = (text: string): string => `\u001b[4m${text}\u001b[24m`;
const MARGIN = 2;

// Word-wraps runs of styled text to a width, noting where each clickable run lands.
function wrap(
  runs: Run[],
  width: number,
  top: number,
): { lines: string[]; hits: TodayHit[] } {
  type Piece = Run & { column: number };
  const rows: Piece[][] = [[]];
  let column = 0;
  for (const run of runs) {
    for (const word of run.text.match(/\S+\s*|\s+/g) ?? []) {
      const size = visibleWidth(word.trimEnd());
      if (column > 0 && column + size > width) {
        rows.push([]);
        column = 0;
      }
      const text = column === 0 ? word.trimStart() : word;
      if (!text) continue;
      rows[rows.length - 1].push({ ...run, text, column });
      column += visibleWidth(text);
    }
  }
  const hits: TodayHit[] = [];
  const lines = rows.map((pieces, index) => {
    let line = "";
    pieces.forEach((piece, at) => {
      const next = pieces[at + 1];
      const joined =
        next && next.style === piece.style && next.action === piece.action;
      const word = piece.text.trimEnd();
      const gap = piece.text.slice(word.length);
      line += joined ? piece.style(piece.text) : piece.style(word) + gap;
      if (!piece.action) return;
      const start = MARGIN + piece.column;
      const end = start + visibleWidth(word);
      const last = hits.at(-1);
      if (
        last &&
        last.row === top + index &&
        last.action === piece.action &&
        last.end <= start
      )
        last.end = end;
      else hits.push({ row: top + index, start, end, action: piece.action });
    });
    return " ".repeat(MARGIN) + line.trimEnd();
  });
  return { lines, hits };
}

function itemStyle(item: BriefingItem | undefined, highlight: boolean) {
  if (!item) return plain;
  if (item.state !== "open") return (text: string) => dim(underline(text));
  return highlight
    ? (text: string) => orange(underline(text))
    : (text: string) => blue(underline(text));
}

const LOADING = "Reading what changed in your project…";
const WRITING = "Writing today's briefing…";
const WRITE_FAILED =
  "Couldn't write today's briefing. Type below to start a chat.";

const ERRORS: Record<Extract<TodayState, { kind: "error" }>["reason"], string> =
  {
    unavailable:
      "Today isn't available for this project. Type below to start a chat.",
    signIn: "Sign out with /logout and sign in again to see Today.",
    failed: "Couldn't load Today. Type below to start a chat.",
  };

// The briefing laid out for a pane: the greeting, headline, progress, linked paragraphs and the Inbox line.
export function todayLines(
  state: TodayState,
  width: number,
  hour: number,
): { lines: string[]; hits: TodayHit[] } {
  const inner = Math.max(10, width - MARGIN * 2);
  const lines: string[] = [""];
  const hits: TodayHit[] = [];
  const add = (runs: Run[]): void => {
    const wrapped = wrap(runs, inner, lines.length);
    lines.push(...wrapped.lines);
    hits.push(...wrapped.hits);
  };
  const firstName = state.kind === "ready" ? state.firstName : null;
  add([{ text: greeting(hour, firstName), style: bold }]);
  lines.push("");
  if (state.kind !== "ready") {
    add([
      {
        text: state.kind === "loading" ? LOADING : ERRORS[state.reason],
        style: dim,
      },
    ]);
    return { lines, hits };
  }
  const { briefing } = state;
  if (briefing.paragraphs.length === 0) {
    add([
      {
        text: briefing.status === "failed" ? WRITE_FAILED : WRITING,
        style: dim,
      },
    ]);
    return { lines, hits };
  }
  add([{ text: briefing.headline, style: plain }]);
  if (briefing.items.length > 0) {
    const done = briefing.items.filter((item) => item.state !== "open").length;
    add([{ text: `${done} of ${briefing.items.length} done`, style: dim }]);
  }
  const items = new Map(briefing.items.map((item) => [item.key, item]));
  for (const paragraph of briefing.paragraphs) {
    lines.push("");
    add(
      paragraph.map((segment) => {
        const item = segment.item_key ? items.get(segment.item_key) : undefined;
        return {
          text: segment.text,
          style: itemStyle(item, segment.highlight),
          ...(item ? { action: { kind: "item", item } as const } : {}),
        };
      }),
    );
  }
  lines.push("");
  const more = briefing.more_reports_count;
  add([
    ...(more > 0
      ? [
          {
            text: `${more} more for you in the Inbox`,
            style: (text: string) => orange(underline(text)),
            action: { kind: "inbox" } as const,
          },
          { text: ". Or ", style: dim },
        ]
      : [{ text: "Or ", style: dim }]),
    {
      text: "ask PostHog AI to walk you through it",
      style: underline,
      action: { kind: "ask" } as const,
    },
    { text: ".", style: dim },
  ]);
  return { lines, hits };
}

export function todayHitAt(
  hits: TodayHit[],
  row: number,
  column: number,
): TodayAction | null {
  return (
    hits.find(
      (hit) => hit.row === row && column >= hit.start && column < hit.end,
    )?.action ?? null
  );
}

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

export interface TodayUser {
  teamId: number;
  firstName: string | null;
}

// Reads the day's briefing and a report's suggested questions for the signed-in user.
export class TodayClient {
  constructor(
    private readonly fetch: Fetch,
    private readonly apiHost: string,
    private readonly user: () => Promise<TodayUser>,
    private readonly timeZone: string = Intl.DateTimeFormat().resolvedOptions()
      .timeZone,
  ) {}

  async load(): Promise<TodayState> {
    try {
      const user = await this.user();
      const response = await this.fetch(
        `${this.apiHost}/api/projects/${user.teamId}/today/briefing/?timezone=${encodeURIComponent(this.timeZone)}`,
      );
      if (response.status === 404)
        return { kind: "error", reason: "unavailable" };
      if (response.status === 403) return { kind: "error", reason: "signIn" };
      if (!response.ok) return { kind: "error", reason: "failed" };
      return {
        kind: "ready",
        briefing: (await response.json()) as Briefing,
        firstName: user.firstName,
      };
    } catch {
      return { kind: "error", reason: "failed" };
    }
  }

  // The report's own suggested questions, or the web app's defaults when it has none or cannot be read.
  async questions(item: BriefingItem): Promise<string[]> {
    const id = item.key.startsWith("report:") ? item.key.slice(7) : null;
    if (!id) return DEFAULT_REPORT_QUESTIONS;
    try {
      const { teamId } = await this.user();
      const response = await this.fetch(
        `${this.apiHost}/api/projects/${teamId}/signals/reports/${id}/`,
      );
      if (!response.ok) return DEFAULT_REPORT_QUESTIONS;
      const report = (await response.json()) as {
        suggested_prompts?: unknown;
      };
      const suggested = Array.isArray(report.suggested_prompts)
        ? report.suggested_prompts.filter(
            (prompt): prompt is string =>
              typeof prompt === "string" && prompt.trim() !== "",
          )
        : [];
      return suggested.length > 0 ? suggested : DEFAULT_REPORT_QUESTIONS;
    } catch {
      return DEFAULT_REPORT_QUESTIONS;
    }
  }

  webUrl(path: string): string {
    return `${this.apiHost}${path}`;
  }

  async inboxUrl(): Promise<string> {
    return this.webUrl(`/project/${(await this.user()).teamId}/inbox`);
  }
}
