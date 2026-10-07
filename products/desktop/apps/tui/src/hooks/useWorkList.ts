import type { Task } from "@posthog/shared";
import { useEffect, useRef, useState } from "react";
import { messageOf } from "../errors";
import { LEGACY_PREFIX } from "../localChats";
import type { CloudRuns } from "../runs";
import type { WorkPage } from "../sidebar";
import { findTask, type WorkList } from "../work";

const PAGE_SIZE = 20;
const REFRESH_MS = 10_000;
// Log entries per preloaded run: roughly the last ten messages.
const PREVIEW_ENTRIES = 300;
const EMPTY_PAGE: WorkPage = {
  tasks: null,
  hasMore: false,
  loadingMore: false,
  error: null,
};

export interface WorkListState {
  page: WorkPage;
  // Open tasks fetched one by one because the recent page does not list them.
  known: Map<string, Task>;
  taskOf: (taskId: string | null) => Task | undefined;
  loadMore: () => void;
  reset: () => void;
}

// The recent work list, refreshed on a timer, with each listed cloud run's recent messages preloaded.
export function useWorkList({
  work,
  runs,
  fresh,
  openTaskIds,
  onRefresh,
}: {
  work: WorkList | undefined;
  runs: CloudRuns | undefined;
  // Tasks this app just started or resumed.
  fresh: Map<string, Task>;
  // Tasks that must keep a title and a transcript even when the recent page does not list them.
  openTaskIds: string[];
  onRefresh: () => void;
}): WorkListState {
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [page, setPage] = useState<WorkPage>(EMPTY_PAGE);
  const [known, setKnown] = useState<Map<string, Task>>(new Map());

  useEffect(() => {
    if (!work) return;
    let cancelled = false;
    const refresh = (): void => {
      onRefresh();
      work.listRecent(limit).then(
        ({ tasks, hasMore }) => {
          if (!cancelled) {
            setPage({ tasks, hasMore, loadingMore: false, error: null });
          }
        },
        (error: unknown) => {
          if (!cancelled) {
            setPage((current) => ({
              ...current,
              loadingMore: false,
              error: messageOf(error),
            }));
          }
        },
      );
    };
    refresh();
    const timer = setInterval(refresh, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [work, limit, onRefresh]);

  // Preloads each listed cloud run's recent messages, one at a time, so opening one shows them at once.
  const prefetched = useRef(new Set<string>());
  useEffect(() => {
    const pending = (page.tasks ?? []).flatMap((task) => {
      const run = task.latest_run;
      return run &&
        run.environment !== "local" &&
        !prefetched.current.has(run.id)
        ? [{ taskId: task.id, runId: run.id }]
        : [];
    });
    if (!runs) return;
    for (const { runId } of pending) prefetched.current.add(runId);
    void (async () => {
      for (const { taskId, runId } of pending) {
        await runs.prefetch(taskId, runId, PREVIEW_ENTRIES).catch(() => {
          prefetched.current.delete(runId);
        });
      }
    })();
  }, [runs, page.tasks]);

  // Open tasks outside the recent page are fetched once each.
  const missing = page.tasks
    ? [...new Set(openTaskIds)].filter(
        (id) =>
          !id.startsWith(LEGACY_PREFIX) &&
          !known.has(id) &&
          !fresh.has(id) &&
          !page.tasks?.some((task) => task.id === id),
      )
    : [];
  const missingKey = missing.join();
  useEffect(() => {
    if (!work) return;
    for (const taskId of missingKey ? missingKey.split(",") : []) {
      work.get(taskId).then(
        (task) => setKnown((current) => new Map(current).set(taskId, task)),
        () => {},
      );
    }
  }, [work, missingKey]);

  return {
    page,
    known,
    taskOf: (taskId) => findTask(taskId, { listed: page.tasks, known, fresh }),
    loadMore: () => {
      setPage((current) => ({ ...current, loadingMore: true }));
      setLimit((current) => current + PAGE_SIZE);
    },
    reset: () => {
      setPage(EMPTY_PAGE);
      setKnown(new Map());
    },
  };
}
