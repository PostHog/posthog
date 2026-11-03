import type { TaskActivity } from "@posthog/shared/domain-types";
import { useEffect, useRef, useState } from "react";
import type { WorkList } from "../work";

// The feed is read on the work list's cadence; a mark-read reads it again at once.
const REFRESH_MS = 10_000;

export interface InboxFeed {
  // The server's latest activity per task, for the user.
  rows: Map<string, TaskActivity>;
  // Marks a task's activity so far read on the server, so every client agrees it was actioned.
  markRead: (taskIds: string[]) => void;
}

const sameFeed = (
  a: Map<string, TaskActivity>,
  b: Map<string, TaskActivity>,
): boolean =>
  a.size === b.size &&
  [...b].every(([id, row]) => {
    const was = a.get(id);
    return (
      was?.activity_at === row.activity_at &&
      was.activity_kind === row.activity_kind &&
      was.is_unread === row.is_unread
    );
  });

export function useInboxFeed(work: WorkList | undefined): InboxFeed {
  const [rows, setRows] = useState<Map<string, TaskActivity>>(new Map());
  const refresh = useRef(async (): Promise<void> => {});
  useEffect(() => {
    // A work list without a feed (a test's stub) leaves the inbox to the chats' own logs.
    if (!work?.activity) return;
    let cancelled = false;
    refresh.current = async () => {
      const list = await work.activity().catch(() => null);
      if (cancelled || !list) return;
      const next = new Map(
        list.flatMap((row) => (row.task_id ? [[row.task_id, row]] : [])),
      );
      // An unchanged feed keeps the same map, so nothing re-renders for it.
      setRows((current) => (sameFeed(current, next) ? current : next));
    };
    void refresh.current();
    const timer = setInterval(() => void refresh.current(), REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [work]);
  return {
    rows,
    markRead: (taskIds) => {
      const markers = taskIds.flatMap((taskId) => {
        const row = rows.get(taskId);
        return row ? [{ task_id: taskId, seen_before: row.activity_at }] : [];
      });
      if (markers.length === 0 || !work?.markRead) return;
      // Shown read at once; the server's answer comes back on the next read.
      setRows((current) => {
        const next = new Map(current);
        for (const { task_id } of markers) {
          const row = next.get(task_id);
          if (row) next.set(task_id, { ...row, is_unread: false });
        }
        return next;
      });
      void work.markRead(markers).then(
        () => refresh.current(),
        () => {},
      );
    },
  };
}
