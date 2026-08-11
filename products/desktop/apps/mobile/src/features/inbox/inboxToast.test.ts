import { describe, expect, it } from "vitest";
import {
  type InboxToast,
  isUndoable,
  TASK_TOAST_MS,
  toastAutoDismissMs,
  UNDO_WINDOW_MS,
} from "./inboxToast";

const taskPending: InboxToast = { kind: "task_pending", title: "Fix the leak" };
const taskStarted: InboxToast = {
  kind: "task_started",
  taskId: "task-1",
  title: "Fix the leak",
};
const undoDismiss: InboxToast = {
  kind: "undo_dismiss",
  reportId: "report-1",
  title: "Fix the leak",
};

describe("toastAutoDismissMs", () => {
  it.each<[string, InboxToast, number | null]>([
    ["a pending task never times out", taskPending, null],
    ["a started task lingers", taskStarted, TASK_TOAST_MS],
    ["an undo window is short", undoDismiss, UNDO_WINDOW_MS],
  ])("%s", (_name, toast, expected) => {
    expect(toastAutoDismissMs(toast)).toBe(expected);
  });

  it("closes the undo window before the task toast would close", () => {
    // The undo window is the tighter of the two deadlines by design: it is a
    // reversal affordance, not a confirmation to read at leisure.
    expect(UNDO_WINDOW_MS).toBeLessThan(TASK_TOAST_MS);
  });
});

describe("isUndoable", () => {
  it.each<[string, InboxToast, boolean]>([
    ["a dismissal can be undone", undoDismiss, true],
    ["a started task cannot", taskStarted, false],
    ["a pending task cannot", taskPending, false],
  ])("%s", (_name, toast, expected) => {
    expect(isUndoable(toast)).toBe(expected);
  });

  it("narrows to the report id when it returns true", () => {
    const toast: InboxToast = undoDismiss;
    expect(isUndoable(toast) ? toast.reportId : null).toBe("report-1");
  });
});
