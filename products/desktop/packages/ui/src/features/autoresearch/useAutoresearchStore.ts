import {
  type AutoresearchState,
  autoresearchStore,
} from "@posthog/core/autoresearch/autoresearchStore";
import type { AutoresearchRun } from "@posthog/core/autoresearch/schemas";
import { useMemo } from "react";
import { useStore } from "zustand";

export function useAutoresearchStore<T>(
  selector: (state: AutoresearchState) => T,
): T {
  return useStore(autoresearchStore, selector);
}

/** All runs for a task, oldest first. */
export function useAutoresearchRuns(taskId: string): AutoresearchRun[] {
  const runs = useAutoresearchStore((state) => state.runs);
  return useMemo(
    () =>
      Object.values(runs)
        .filter((run) => run.config.taskId === taskId)
        .sort((a, b) => a.startedAt - b.startedAt),
    [runs, taskId],
  );
}

export function useActiveAutoresearchRun(
  taskId: string,
): AutoresearchRun | null {
  return useAutoresearchStore((state) => {
    const runId = state.activeRunIdByTask[taskId];
    return runId ? (state.runs[runId] ?? null) : null;
  });
}
