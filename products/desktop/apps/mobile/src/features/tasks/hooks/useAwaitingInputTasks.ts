import { useMemo } from "react";
import { useTaskSessionStore } from "../stores/taskSessionStore";
import { collectAwaitingInputTaskIds } from "../utils/awaitingInput";

/**
 * Only covers tasks with a live session in this app — a task the user has not
 * opened has no stream to say it is blocked, and `latest_run.status` stays
 * `in_progress` while an agent waits, so it cannot stand in for the signal.
 */
export function useAwaitingInputTaskIds(): ReadonlySet<string> {
  const sessions = useTaskSessionStore((state) => state.sessions);
  return useMemo(() => collectAwaitingInputTaskIds(sessions), [sessions]);
}
