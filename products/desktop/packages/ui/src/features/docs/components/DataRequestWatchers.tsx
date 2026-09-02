import type { DocSchemas } from "@posthog/api-client/docs";
import type { Task } from "@posthog/shared/domain-types";
import { useEffect } from "react";
import { agentStateOf } from "../hooks/useDocThread";

/** A data point the page is watching: still a request, or a value that may change. */
export interface WatchedDataPoint {
  requestId: string;
  kind: "request" | "value";
  /** The query the page shows now, so a new one from the thread is told apart. */
  query: string | null;
}

export type DataAnswer =
  /** The query the thread ended with. The page keeps it and runs it on every read. */
  | { kind: "value"; query: string; label: string; note: string }
  /** The agent's run ended and the thread has no query. */
  | { kind: "ended"; failed: boolean }
  /** The agent wrote in the thread but has not handed in a query yet. */
  | { kind: "reply" };

/**
 * Turns the page's data requests into data points as their threads answer.
 *
 * The answer lives on the thread, where the agent's tool put it, so every window
 * resolves the same way: the one that asked, one that reloaded mid-run, and one
 * that never asked at all.
 */
export function DataRequestWatchers({
  watched,
  threads,
  tasks,
  onAnswer,
}: {
  watched: WatchedDataPoint[];
  threads: DocSchemas.DiscussionThread[];
  tasks: Task[];
  onAnswer: (requestId: string, answer: DataAnswer) => void;
}) {
  useEffect(() => {
    for (const point of watched) {
      const thread = threads.find(
        (candidate) =>
          candidate.kind === "data" && candidate.anchor_key === point.requestId,
      );
      if (!thread) continue;
      const answer = thread.answer;
      if (answer && answer.query !== point.query) {
        onAnswer(point.requestId, {
          kind: "value",
          query: answer.query,
          label: answer.label,
          note: answer.note,
        });
        continue;
      }
      if (point.kind !== "request") continue;
      const task = thread.task_id
        ? tasks.find((entry) => entry.id === thread.task_id)
        : undefined;
      const state = agentStateOf(thread, task);
      if (state === "done" || state === "failed") {
        onAnswer(point.requestId, {
          kind: "ended",
          failed: state === "failed",
        });
        continue;
      }
      if (thread.replies.some((post) => post.author_kind === "agent")) {
        onAnswer(point.requestId, { kind: "reply" });
      }
    }
  }, [watched, threads, tasks, onAnswer]);

  return null;
}
