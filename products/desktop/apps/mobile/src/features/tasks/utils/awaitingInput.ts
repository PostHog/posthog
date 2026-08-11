import { isTerminalStatus, type Task } from "@posthog/shared";
import type { TaskSession } from "../stores/taskSessionStore";

/** The subset of a task this decision reads, so tests can stay minimal. */
type AwaitingInputTask = Pick<Task, "id" | "latest_run">;

/**
 * A session whose stream is gone stopped tracking the run, so its
 * `isAwaitingUserInput` is frozen at whatever it was when the stream died.
 */
function isLiveSession(
  session: TaskSession | undefined,
): session is TaskSession {
  return (
    session !== undefined &&
    session.status !== "error" &&
    session.status !== "disconnected"
  );
}

/**
 * Whether a task is blocked on its user.
 *
 * Two sources say so and they disagree by design. A live session in this app is
 * the fresher of the two — it reflects events the list has not refetched yet —
 * so when one exists it decides on its own. Without one (a task the user has
 * never opened on this device, or one whose stream died) the server's persisted
 * marker is the only signal, since `latest_run.status` stays `in_progress`
 * while an agent waits.
 */
export function isTaskAwaitingUserInput(
  task: AwaitingInputTask | undefined,
  session: TaskSession | undefined,
): boolean {
  if (isLiveSession(session)) {
    // A run that has reached a terminal status is waiting on nobody, however
    // its log ended.
    return Boolean(session.isAwaitingUserInput) && !session.terminalStatus;
  }
  const run = task?.latest_run;
  if (!run || isTerminalStatus(run.status)) return false;
  return run.state?.awaiting_user_input === true;
}

/**
 * Task ids blocked on the user, across both signals. `tasks` covers everything
 * the list knows about; sessions for tasks outside that set (filtered out, or
 * beyond the fetch window) still count.
 */
export function collectAwaitingInputTaskIds(
  sessions: Record<string, TaskSession>,
  tasks: readonly AwaitingInputTask[] = [],
): Set<string> {
  // Sessions are keyed by run, so a task with more than one collapses to the
  // last inserted — which is the newest run, the one the list should reflect.
  const sessionsByTaskId = new Map<string, TaskSession>();
  for (const session of Object.values(sessions)) {
    sessionsByTaskId.set(session.taskId, session);
  }

  const taskIds = new Set<string>();
  const listedTaskIds = new Set<string>();
  for (const task of tasks) {
    listedTaskIds.add(task.id);
    if (isTaskAwaitingUserInput(task, sessionsByTaskId.get(task.id))) {
      taskIds.add(task.id);
    }
  }
  for (const [taskId, session] of sessionsByTaskId) {
    if (listedTaskIds.has(taskId)) continue;
    if (isTaskAwaitingUserInput(undefined, session)) taskIds.add(taskId);
  }
  return taskIds;
}
