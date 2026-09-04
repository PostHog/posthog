import type { SignalReport, Task } from "@posthog/shared/domain-types";
import type { ChannelFeedSystemMessage } from "@posthog/ui/features/canvas/hooks/useChannelFeedMessages";

// Injected context wrappers a prompt may carry (Slack thread history, a
// channel's CONTEXT.md, canvas instructions, saved personalization, the
// onboarding session's whole brief). The feed shows what the user actually
// asked, so these are stripped and the timeline renders them as their own
// collapsible surfaces. Nobody asked for the onboarding brief, so it has no
// surface of its own and the card falls back to its title.
const CONTEXT_BLOCK_REGEX =
  /<(slack_thread_context|channel_context|canvas_generation_instructions|user_custom_instructions|onboarding_brief)\b[^>]*>[\s\S]*?<\/\1>/g;

export function stripContextBlocks(text: string): string {
  return text
    .replace(CONTEXT_BLOCK_REGEX, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

// A single feed entry — a task card, a report card, or a synthetic system row —
// tagged with the timestamp used to interleave them.
export type FeedEntry =
  | { kind: "task"; id: string; createdAt: string; task: Task }
  | { kind: "report"; id: string; createdAt: string; report: SignalReport }
  | {
      kind: "system";
      id: string;
      createdAt: string;
      message: ChannelFeedSystemMessage;
    };

/** Which entry kinds the feed shows. Sessions cover tasks and their system rows. */
export type FeedKindFilter = "all" | "sessions" | "reports";

export function feedEntryMatchesKind(
  entry: FeedEntry,
  filter: FeedKindFilter,
): boolean {
  if (filter === "all") return true;
  if (filter === "reports") return entry.kind === "report";
  return entry.kind !== "report";
}

// Merge tasks + reports + system rows into one newest-first list. ISO timestamps
// sort lexically, so a plain string compare is chronological. Announcements are
// posted 1ms before the task they describe; if the backend truncates that
// sub-second offset the timestamps tie, so break ties task-first to keep the
// announcement directly under its card.
export function mergeFeedEntries(
  tasks: Task[],
  systemMessages: ChannelFeedSystemMessage[],
  reports: SignalReport[] = [],
): FeedEntry[] {
  const merged: FeedEntry[] = [
    ...tasks.map((task) => ({
      kind: "task" as const,
      id: task.id,
      createdAt: task.created_at,
      task,
    })),
    ...reports.map((report) => ({
      kind: "report" as const,
      id: report.id,
      createdAt: report.created_at,
      report,
    })),
    ...systemMessages.map((message) => ({
      kind: "system" as const,
      id: message.id,
      createdAt: message.createdAt,
      message,
    })),
  ];
  merged.sort(
    (a, b) =>
      b.createdAt.localeCompare(a.createdAt) ||
      (a.kind === b.kind
        ? 0
        : a.kind === "task"
          ? -1
          : b.kind === "task"
            ? 1
            : 0),
  );
  return merged;
}
