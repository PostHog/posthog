import { readPrUrls } from "@posthog/shared";
import type {
  TaskRunEnvironment,
  TaskRunStatus,
} from "@posthog/shared/domain-types";
import {
  type CellStatus,
  deriveStatus,
  type SessionStatusInput,
} from "../command-center/status";
import type {
  CanvasTaskSummary,
  CanvasTasksInput,
  CanvasTasksResult,
} from "./freeformSchemas";

// Structural inputs (like buildSidebarData's FullTask/TaskSession) so the UI
// can pass its real Task/AgentSession values and tests can fake minimal ones.

export interface CanvasTaskSource {
  id: string;
  title: string;
  repository?: string | null;
  created_at: string;
  updated_at: string;
  latest_run?: {
    status?: TaskRunStatus | null;
    environment?: TaskRunEnvironment | null;
    output?: Record<string, unknown> | null;
  } | null;
}

export interface CanvasTaskSession extends SessionStatusInput {
  taskId?: string;
  cloudOutput?: Record<string, unknown> | null;
}

// A canvas that doesn't ask for a limit still gets a bounded board: recent
// parallel work, not the whole task history.
const DEFAULT_LIMIT = 50;

// Coarsens a run's lifecycle status into the display status when the task has
// no live session to derive from (e.g. a cloud run finished while the app was
// closed). Mirrors what the Command Center would show once a session attaches.
function statusFromRun(
  runStatus: TaskRunStatus | null | undefined,
): CellStatus {
  switch (runStatus) {
    case "completed":
      return "completed";
    case "failed":
    case "cancelled":
      return "error";
    case "in_progress":
    case "queued":
      return "running";
    default:
      return "idle";
  }
}

/**
 * Projects the user's tasks + live session state into the `ph.tasks` wire shape
 * — the read behind a canvas task board. Sessions are keyed by run id (the
 * session store's shape) and matched to tasks via their `taskId`, exactly like
 * the Command Center's join. Sorted most recently updated first, then capped.
 */
export function buildCanvasTaskSummaries(
  tasks: CanvasTaskSource[],
  sessions: Record<string, CanvasTaskSession>,
  input: CanvasTasksInput = {},
): CanvasTasksResult {
  const sessionByTaskId = new Map<string, CanvasTaskSession>();
  for (const session of Object.values(sessions)) {
    if (session.taskId) sessionByTaskId.set(session.taskId, session);
  }

  const limit = input.limit ?? DEFAULT_LIMIT;
  const summaries = [...tasks]
    .sort(
      (a, b) =>
        new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
    )
    .slice(0, limit)
    .map((task): CanvasTaskSummary => {
      const session = sessionByTaskId.get(task.id);
      const runStatus = task.latest_run?.status;
      // Live session signals (waiting/running/error/completed) win. But a
      // session that is merely idle-connected says nothing about the outcome —
      // a local session stays connected after its prompt finishes — so a
      // terminal run record shows the landed result instead. A non-terminal
      // run record never overrides an idle session: the session is fresher.
      let status = session ? deriveStatus(session) : statusFromRun(runStatus);
      const runIsTerminal =
        runStatus === "completed" ||
        runStatus === "failed" ||
        runStatus === "cancelled";
      if (session && status === "idle" && runIsTerminal) {
        status = statusFromRun(runStatus);
      }
      return {
        id: task.id,
        title: task.title,
        status,
        runStatus: task.latest_run?.status ?? null,
        environment: task.latest_run?.environment ?? null,
        repository: task.repository ?? null,
        prUrl:
          readPrUrls(task.latest_run?.output)[0] ??
          readPrUrls(session?.cloudOutput)[0] ??
          null,
        needsPermission: (session?.pendingPermissions?.size ?? 0) > 0,
        isGenerating: session?.isPromptPending ?? false,
        createdAt: task.created_at,
        updatedAt: task.updated_at,
      };
    });

  return { tasks: summaries };
}
