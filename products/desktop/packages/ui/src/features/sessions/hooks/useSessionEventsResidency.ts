import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import { useEffect } from "react";

/** Mounted viewers per taskId, so one view unmounting can't schedule an
 * eviction out from under another still-mounted view of the same task. */
const viewerCounts = new Map<string, number>();

/**
 * Ties a task's transcript memory to whether its view is mounted: reloads the
 * transcript from disk on view (if it was freed while backgrounded) and
 * schedules it to be freed a short while after the last view unmounts. Only
 * disconnected background sessions are actually evicted — see
 * {@link SessionService.scheduleEventEviction}.
 */
export function useSessionEventsResidency(taskId: string | undefined): void {
  const sessionService = useService<SessionService>(SESSION_SERVICE);

  useEffect(() => {
    if (!taskId) return;
    viewerCounts.set(taskId, (viewerCounts.get(taskId) ?? 0) + 1);
    void sessionService.ensureEventsLoaded(taskId);
    return () => {
      const remaining = (viewerCounts.get(taskId) ?? 1) - 1;
      if (remaining > 0) {
        viewerCounts.set(taskId, remaining);
        return;
      }
      viewerCounts.delete(taskId);
      sessionService.scheduleEventEviction(taskId);
    };
  }, [taskId, sessionService]);
}
