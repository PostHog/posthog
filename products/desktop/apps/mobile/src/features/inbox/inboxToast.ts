/**
 * The single toast slot at the bottom of the inbox card view.
 *
 * Two very different things want that slot: the "task started" confirmation a
 * right-swipe produces, and the undo window a left-swipe opens. Modelling them
 * as one discriminated union rather than two overlapping banners is what keeps
 * a dismissal from stacking on top of a task confirmation — the newer swipe
 * simply replaces the older toast, which is also what the user expects, since
 * only the most recent swipe is undoable.
 */

/**
 * How long a dismissal stays undoable. Long enough to notice the card leave
 * and change your mind, short enough that the slot is free again before the
 * next swipe lands on it.
 */
export const UNDO_WINDOW_MS = 6_000;

/** How long the "task started" confirmation and its link stay reachable. */
export const TASK_TOAST_MS = 10_000;

/** A task is being created — no auto-dismiss; the result replaces it. */
export interface TaskPendingToast {
  kind: "task_pending";
  title: string;
}

/** A task was created and can be opened. */
export interface TaskStartedToast {
  kind: "task_started";
  taskId: string;
  title: string;
}

/** A report was dismissed and can still be brought back. */
export interface UndoDismissToast {
  kind: "undo_dismiss";
  reportId: string;
  title: string;
}

export type InboxToast = TaskPendingToast | TaskStartedToast | UndoDismissToast;

/**
 * How long the toast should stay up, or `null` when it must not time out.
 *
 * A pending task has no deadline on purpose: the create-and-run round trip has
 * no upper bound, and a spinner that vanishes mid-flight reads as a failure.
 * It is always superseded by the started toast or cleared by the error path.
 */
export function toastAutoDismissMs(toast: InboxToast): number | null {
  switch (toast.kind) {
    case "task_pending":
      return null;
    case "task_started":
      return TASK_TOAST_MS;
    case "undo_dismiss":
      return UNDO_WINDOW_MS;
  }
}

/** Accepts are not undoable — the task already exists by the time we say so. */
export function isUndoable(toast: InboxToast): toast is UndoDismissToast {
  return toast.kind === "undo_dismiss";
}
