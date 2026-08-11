import { useMemo } from "react";
import { useTaskSessionStore } from "../stores/taskSessionStore";
import { collectAwaitingInputTaskIds } from "../utils/awaitingInput";
import { useTasks } from "./useTasks";

/**
 * Tasks blocked on the user, from both the live sessions in this app and the
 * server's persisted marker on `latest_run.state`. The server signal is what
 * covers tasks the user has never opened here — they have no stream to say they
 * are blocked, and `latest_run.status` stays `in_progress` while an agent waits.
 *
 * Sourcing the task list here (rather than taking it as an argument) keeps every
 * awaiting-input affordance — list rows, the pinned rail — on one signal. The
 * query is shared, so this adds no fetch.
 */
export function useAwaitingInputTaskIds(): ReadonlySet<string> {
  const sessions = useTaskSessionStore((state) => state.sessions);
  const { allTasks } = useTasks();
  return useMemo(
    () => collectAwaitingInputTaskIds(sessions, allTasks),
    [sessions, allTasks],
  );
}
