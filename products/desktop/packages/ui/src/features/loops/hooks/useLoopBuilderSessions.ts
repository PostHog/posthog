import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { useTaskSummaries } from "@posthog/ui/features/tasks/useTasks";
import { useEffect, useMemo, useState } from "react";
import {
  type BuilderRunSummaries,
  FRESH_SESSION_GRACE_MS,
  isBuilderSessionEnded,
} from "../loopBuilderLiveness";
import {
  type LoopBuilderSession,
  useLoopBuilderSessionStore,
} from "../loopBuilderSessionStore";

/**
 * The current identity's builder sessions whose cloud run is still alive.
 * Sessions whose sandbox has shut down (run completed, failed, cancelled, or
 * task archived or deleted) are pruned from the persisted store as their status
 * comes in, so the "in progress" list never offers a resume into a dead
 * session. Other identities' sessions are never shown or pruned: the summaries
 * this hook queries are only authoritative for the signed-in account. The
 * liveness decision itself is the pure `isBuilderSessionEnded`.
 *
 * `isSettled` is false until the persisted store has hydrated and the
 * summaries backing the liveness check have resolved, i.e. while `sessions`
 * may still be missing entries or contain entries about to be pruned.
 */
export function useLoopBuilderSessions(): {
  sessions: LoopBuilderSession[];
  isSettled: boolean;
} {
  const identity = useAuthStateValue(getAuthIdentity);
  const allSessions = useLoopBuilderSessionStore((state) => state.sessions);
  const hasHydrated = useLoopBuilderSessionStore((state) => state._hasHydrated);
  const sessions = useMemo(
    () =>
      identity
        ? allSessions.filter((session) => session.identity === identity)
        : [],
    [allSessions, identity],
  );
  const archivedTaskIds = useArchivedTaskIds();
  const taskIds = useMemo(
    () => sessions.map((session) => session.taskId),
    [sessions],
  );
  const { data, isSuccess, isPlaceholderData } = useTaskSummaries(taskIds);

  const summaries = useMemo<BuilderRunSummaries | null>(() => {
    // Placeholder data is the previous id set's response; judging liveness on
    // it would prune a just-added session that isn't in that response yet.
    if (!isSuccess || isPlaceholderData || !data) return null;
    return new Map(
      data.map((summary) => [
        summary.id,
        summary.latest_run
          ? {
              environment: summary.latest_run.environment,
              status: summary.latest_run.status,
            }
          : null,
      ]),
    );
  }, [isSuccess, isPlaceholderData, data]);

  // Grace expiry doesn't produce a re-render by itself (polled summaries keep
  // their identity when nothing changed), so schedule one for the soonest
  // boundary; `now` is otherwise only refreshed by real data changes.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const waits = sessions
      .map((session) => session.startedAt + FRESH_SESSION_GRACE_MS - now)
      .filter((wait) => wait > 0);
    if (waits.length === 0) return;
    const timer = setTimeout(() => setNow(Date.now()), Math.min(...waits) + 50);
    return () => clearTimeout(timer);
  }, [sessions, now]);

  useEffect(() => {
    if (!summaries || !identity) return;
    const store = useLoopBuilderSessionStore.getState();
    for (const session of store.sessions) {
      if (session.identity !== identity) continue;
      if (isBuilderSessionEnded(session, summaries, archivedTaskIds, now)) {
        store.removeSession(session.taskId);
      }
    }
  }, [summaries, archivedTaskIds, now, identity]);

  const liveSessions = useMemo(() => {
    if (!summaries) {
      return sessions.filter((session) => !archivedTaskIds.has(session.taskId));
    }
    return sessions.filter(
      (session) =>
        !isBuilderSessionEnded(session, summaries, archivedTaskIds, now),
    );
  }, [sessions, summaries, archivedTaskIds, now]);

  return {
    sessions: liveSessions,
    isSettled: hasHydrated && (sessions.length === 0 || summaries !== null),
  };
}
