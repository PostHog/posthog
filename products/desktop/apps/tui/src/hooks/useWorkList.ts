import type { Task } from "@posthog/shared";
import { useEffect, useRef, useState } from "react";
import { messageOf } from "../errors";
import { LEGACY_PREFIX } from "../localChats";
import type { ChatScope } from "../prefs";
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
  scope = "mine",
}: {
  work: WorkList | undefined;
  runs: CloudRuns | undefined;
  // Tasks this app just started or resumed.
  fresh: Map<string, Task>;
  // Tasks that must keep a title and a transcript even when the recent page does not list them.
  openTaskIds: string[];
  onRefresh: () => void;
  // Whose chats the list holds; a switch starts the list over from its first page.
  scope?: ChatScope;
}): WorkListState {
  // The limit and the page belong to the tab they were fetched for; another tab starts over from its first page.
  const [paged, setPaged] = useState({ scope, limit: PAGE_SIZE });
  const limit = paged.scope === scope ? paged.limit : PAGE_SIZE;
  const [loaded, setLoaded] = useState({ scope, page: EMPTY_PAGE });
  const page = loaded.scope === scope ? loaded.page : EMPTY_PAGE;
  const [known, setKnown] = useState<Map<string, Task>>(new Map());

  useEffect(() => {
    if (!work) return;
    let cancelled = false;
    const refresh = (): void => {
      onRefresh();
      work.listRecent(limit, scope).then(
        ({ tasks, hasMore, me }) => {
          if (!cancelled) {
            setLoaded({
              scope,
              page: { tasks, hasMore, me, loadingMore: false, error: null },
            });
          }
        },
        (error: unknown) => {
          if (!cancelled) {
            setLoaded((current) => ({
              scope,
              page: {
                ...(current.scope === scope ? current.page : EMPTY_PAGE),
                loadingMore: false,
                error: messageOf(error),
              },
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
  }, [work, limit, scope, onRefresh]);

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
      setLoaded({ scope, page: { ...page, loadingMore: true } });
      setPaged({ scope, limit: limit + PAGE_SIZE });
    },
    reset: () => {
      setLoaded({ scope, page: EMPTY_PAGE });
      setKnown(new Map());
    },
  };
}
