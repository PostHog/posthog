import type { DocSchemas } from "@posthog/api-client/docs";

export type TimelineKind =
  | "started"
  | "brief"
  | "check"
  | "moved"
  | "stale"
  | "report"
  | "verdict"
  | "scout"
  | "stopped"
  | "paused"
  | "resumed"
  | "comment";

export interface TimelineEntry {
  id: string;
  at: string;
  kind: TimelineKind;
  /** One line. A report keeps its whole text in `body`. */
  title: string;
  body?: string;
  who?: string;
}

const EVENT_KIND: Record<DocSchemas.WatchEvent, TimelineKind> = {
  brief: "brief",
  check: "check",
  moved: "moved",
  stale: "stale",
  report: "report",
  verdict: "verdict",
  scout: "scout",
  stopped: "stopped",
  paused: "paused",
  resumed: "resumed",
};

function formatValue(value: number | null): string {
  if (value === null) return "—";
  return Number.isInteger(value)
    ? value.toLocaleString()
    : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function firstLine(text: string): string {
  return (
    text
      .replace(/\*\*/g, "")
      .split("\n")
      .find((line) => line.trim()) ?? ""
  );
}

/**
 * Everything that happened to a watch, oldest first: the posts the watch wrote,
 * the people's and the agent's words, and every daily check the evidence
 * history remembers, including the quiet ones the thread never posted.
 */
export function watchTimeline(
  thread: DocSchemas.DiscussionThread,
  personName: (person: DocSchemas.DocPerson | null) => string,
): TimelineEntry[] {
  const entries: TimelineEntry[] = [
    {
      id: `${thread.id}:start`,
      at: thread.created_at,
      kind: "started",
      title: "Watch started",
      who: personName(thread.created_by),
    },
  ];

  for (const post of thread.replies) {
    const kind = post.event ? EVENT_KIND[post.event] : null;
    if (kind === "report") {
      entries.push({
        id: post.id,
        at: post.created_at,
        kind,
        title: firstLine(post.content),
        body: post.content,
        who: "Scout",
      });
      continue;
    }
    if (kind) {
      entries.push({
        id: post.id,
        at: post.created_at,
        kind,
        title: post.content,
        who:
          post.author_kind === "human"
            ? personName(post.created_by)
            : post.author_kind === "agent"
              ? "Agent"
              : undefined,
      });
      continue;
    }
    if (post.author_kind === "system") continue;
    entries.push({
      id: post.id,
      at: post.created_at,
      kind: "comment",
      title: firstLine(post.content),
      body: post.content,
      who: post.author_kind === "agent" ? "Agent" : personName(post.created_by),
    });
  }

  // The checks that held were never posted; the evidence history has them.
  const checks = new Map<string, string[]>();
  for (const evidence of thread.watch?.brief?.evidence ?? []) {
    for (const [at, value] of evidence.history) {
      const lines = checks.get(at) ?? [];
      lines.push(
        `${evidence.label || "evidence"} ${formatValue(typeof value === "number" ? value : null)}`,
      );
      checks.set(at, lines);
    }
  }
  const noted = new Set(
    entries
      .filter((entry) => entry.kind === "moved" || entry.kind === "check")
      .map((entry) => Date.parse(entry.at)),
  );
  for (const [at, lines] of checks) {
    const time = Date.parse(at);
    // A check that also produced a post within a few seconds is already there.
    if ([...noted].some((seen) => Math.abs(seen - time) < 10_000)) continue;
    entries.push({
      id: `check:${at}`,
      at,
      kind: "check",
      title: lines.join(" · "),
    });
  }

  return entries.sort(
    (left, right) => Date.parse(left.at) - Date.parse(right.at),
  );
}
