/**
 * Collapses a stretch of repetitive event rows into one row per thing that happened.
 *
 * A run that pushes twenty times writes twenty rows saying "1 commit pushed", which buries
 * everything else in the panel and says less than one row saying "20 commits pushed". Only a
 * run of adjacent rows collapses, so a group never reaches across a prompt, a reply, a run
 * start or anything else the reader stops on.
 */

import {
  type ActivityEvent,
  prRepository,
} from "@posthog/core/canvas/activityEvents";
import type {
  ActivityRow,
  CommentThreadLike,
} from "@posthog/core/canvas/activityTimeline";
import type { ThreadMessageLike } from "@posthog/core/canvas/threadTimeline";

/** The kinds that collapse. Every other kind names something the reader has to act on. */
export type GroupableActivityEvent = Extract<
  ActivityEvent,
  { kind: "commits_pushed" | "pr_created" | "pr_merged" | "pr_closed" }
>;

export type GroupedActivityRow<
  TMessage extends ThreadMessageLike = ThreadMessageLike,
  TComment extends CommentThreadLike = CommentThreadLike,
> =
  | ActivityRow<TMessage, TComment>
  | {
      kind: "event_group";
      key: string;
      /** The newest member's, so the row reads as when the run of them ended. */
      ts: number;
      events: GroupableActivityEvent[];
    };

/** What a group of this kind is keyed on: two rows collapse only if they answer the same. */
function groupKey(event: GroupableActivityEvent): string {
  // Two pushes to one branch are one piece of news; two branches are two.
  if (event.kind === "commits_pushed") {
    return `commits_pushed:${event.payload.branch}`;
  }
  return `${event.kind}:${prRepository(event.payload) ?? ""}`;
}

export function groupActivityRows<
  TMessage extends ThreadMessageLike,
  TComment extends CommentThreadLike,
>(
  rows: ActivityRow<TMessage, TComment>[],
): GroupedActivityRow<TMessage, TComment>[] {
  const grouped: GroupedActivityRow<TMessage, TComment>[] = [];
  let index = 0;

  while (index < rows.length) {
    const row = rows[index];
    const event = row ? groupableEvent(row) : null;
    if (!row || !event) {
      if (row) grouped.push(row);
      index += 1;
      continue;
    }
    // The run is every groupable row up to the next one that isn't. Grouping within the run
    // rather than only over neighbours collapses pushes that a pull request landed between,
    // which is the shape a stack of branches arrives in.
    let end = index;
    const members = new Map<
      string,
      {
        first: ActivityRow<TMessage, TComment>;
        events: GroupableActivityEvent[];
        ts: number;
      }
    >();
    while (end < rows.length) {
      const candidate = rows[end];
      const candidateEvent = candidate ? groupableEvent(candidate) : null;
      if (!candidate || !candidateEvent) break;
      const key = groupKey(candidateEvent);
      const bucket = members.get(key);
      if (bucket) {
        bucket.events.push(candidateEvent);
        bucket.ts = Math.max(bucket.ts, candidate.ts);
      } else {
        members.set(key, {
          first: candidate,
          events: [candidateEvent],
          ts: candidate.ts,
        });
      }
      end += 1;
    }

    // Insertion order, so each group sits where the first of its members did.
    for (const bucket of members.values()) {
      if (bucket.events.length === 1) {
        grouped.push(bucket.first);
        continue;
      }
      grouped.push({
        kind: "event_group",
        key: `group-${bucket.first.key}`,
        ts: bucket.ts,
        events: bucket.events,
      });
    }
    index = end;
  }

  return grouped;
}

function groupableEvent<
  TMessage extends ThreadMessageLike,
  TComment extends CommentThreadLike,
>(row: ActivityRow<TMessage, TComment>): GroupableActivityEvent | null {
  if (row.kind !== "event") return null;
  const event = row.event;
  switch (event.kind) {
    case "commits_pushed":
    case "pr_created":
    case "pr_merged":
    case "pr_closed":
      return event;
    default:
      return null;
  }
}
