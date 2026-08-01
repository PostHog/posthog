import type { DashboardSummary } from "@posthog/core/canvas/dashboardSchemas";
import {
  deriveTaskData,
  narrowFullTask,
  type TaskSession,
} from "@posthog/core/sidebar/buildSidebarData";
import type { Task } from "@posthog/shared/domain-types";
import { useSidebarSessionMap } from "@posthog/ui/features/sidebar/useSidebarSessionMap";
import { useTaskViewed } from "@posthog/ui/features/sidebar/useTaskViewed";
import { useMemo } from "react";

const EMPTY_SET: ReadonlySet<string> = new Set();
const EMPTY_STRING_MAP: ReadonlyMap<string, string> = new Map();

// Which canvas generation tasks should be shown nested under their canvas in
// the channel tree. A generation task nests while it's actively generating, and
// stays nested afterwards until the user has actually looked at the task — i.e.
// there's activity they haven't seen. (A never-viewed task counts as unseen, so
// it stays put rather than vanishing the instant it finishes.) The task being
// viewed right now stays nested too, so it doesn't jump out from under the
// canvas while the user is still on its task view (opening it marks it viewed);
// it drops into the channel's regular list once they navigate away. Sending a
// follow-up starts it generating again and re-nests it.
//
// Derived in bulk from one sessions + timestamps read (rather than per row) so
// the channel can both render the nested rows and dedupe them out of the flat
// task list from a single source of truth, with no chance of the two diverging.
export function useNestedGenerationTaskIds(
  dashboards: DashboardSummary[],
  tasks: Task[] | undefined,
  openTaskId: string | undefined,
): ReadonlySet<string> {
  // Signature-guarded map: stable across the per-token event appends of a live
  // turn, so this hook (mounted in the always-present channel tree) recomputes
  // only when a nesting-relevant session field changes — not 60x/sec.
  const sessionByTaskId = useSidebarSessionMap();
  const { timestamps } = useTaskViewed();

  return useMemo(() => {
    const generationTaskIds = dashboards
      .map((d) => d.generationTaskId)
      .filter((id): id is string => !!id);
    if (generationTaskIds.length === 0) return EMPTY_SET;

    const taskById = new Map(tasks?.map((t) => [t.id, t]) ?? []);

    const nested = new Set<string>();
    for (const taskId of generationTaskIds) {
      const task = taskById.get(taskId);
      // Tasks are private to their creator; one that isn't in our list can't be
      // shown (or deduped) — leave it out.
      if (!task) continue;
      const data = deriveTaskData(narrowFullTask(task), {
        session: sessionByTaskId.get(taskId) as TaskSession | undefined,
        workspace: undefined,
        timestamp: timestamps[taskId],
        pinnedIds: EMPTY_SET,
        suspendedIds: EMPTY_SET,
        slackTaskIds: EMPTY_SET,
        slackThreadUrlByTaskId: EMPTY_STRING_MAP,
      });
      // `isUnread` requires a prior view (lastViewedAt set); a never-viewed
      // task isn't "unread" but is still unseen, so check activity-vs-view
      // directly to keep a just-finished, never-opened task nested.
      const lastViewedAt = timestamps[taskId]?.lastViewedAt;
      const hasUnseenActivity =
        lastViewedAt == null || data.lastActivityAt > lastViewedAt;
      if (data.isGenerating || hasUnseenActivity || taskId === openTaskId)
        nested.add(taskId);
    }
    return nested;
  }, [dashboards, tasks, sessionByTaskId, timestamps, openTaskId]);
}
