import { create } from "zustand";
import type { PendingAttachment } from "../composer/attachments/types";

export interface QueuedMessage {
  id: string;
  content: string;
  attachments: PendingAttachment[];
}

const EMPTY: QueuedMessage[] = [];

export type MoveDirection = "up" | "down";

let queueIdCounter = 0;
function nextQueueId(): string {
  queueIdCounter += 1;
  return `queue-${queueIdCounter}`;
}

// A message being edited in place acts as a drain boundary: only the messages
// queued before it may auto-send; it and everything after stay put until the
// edit is saved or cancelled. Returns the full length when nothing is being
// edited (or the edited message has already left the queue). Mirrors
// `sendableQueuePrefixLength` in @posthog/shared, reimplemented here because
// mobile's queue rows (`{id, content, attachments}`) don't match the shared
// `AgentSession` message shape.
function sendablePrefixLength(
  queue: QueuedMessage[],
  editingId: string | undefined,
): number {
  if (!editingId) return queue.length;
  const index = queue.findIndex((m) => m.id === editingId);
  return index === -1 ? queue.length : index;
}

interface MessageQueueState {
  queuesByTaskId: Record<string, QueuedMessage[]>;
  /** Per-task id of the queued message currently open in the composer. */
  editingByTaskId: Record<string, string>;
  enqueue: (
    taskId: string,
    content: string,
    attachments: PendingAttachment[],
  ) => void;
  /**
   * Remove and return queued messages from the head, in FIFO order. With
   * `stopAtEdited`, stops at the in-place edit boundary so the edited message
   * and everything after it stay queued.
   */
  drain: (
    taskId: string,
    options?: { stopAtEdited?: boolean },
  ) => QueuedMessage[];
  /** Restore messages at the head of the queue, e.g. after a failed flush. */
  prepend: (taskId: string, messages: QueuedMessage[]) => void;
  /** Drop a single queued message by id. Clears the edit hold if it targeted it. */
  remove: (taskId: string, messageId: string) => void;
  /** Reorder a queued message one slot up or down; the send order follows. */
  move: (taskId: string, messageId: string, direction: MoveDirection) => void;
  /** Replace a queued message's content/attachments in place, keeping position. */
  update: (
    taskId: string,
    messageId: string,
    patch: { content: string; attachments: PendingAttachment[] },
  ) => void;
  /** Mark a queued message as being edited in the composer (drain boundary). */
  setEditing: (taskId: string, messageId: string) => void;
  /** Release the in-place edit hold. */
  clearEditing: (taskId: string) => void;
  getQueue: (taskId: string) => QueuedMessage[];
}

export const useMessageQueueStore = create<MessageQueueState>((set, get) => ({
  queuesByTaskId: {},
  editingByTaskId: {},
  enqueue: (taskId, content, attachments) =>
    set((state) => ({
      queuesByTaskId: {
        ...state.queuesByTaskId,
        [taskId]: [
          ...(state.queuesByTaskId[taskId] ?? []),
          { id: nextQueueId(), content, attachments },
        ],
      },
    })),
  drain: (taskId, options) => {
    const queued = get().queuesByTaskId[taskId] ?? EMPTY;
    if (queued.length === 0) return EMPTY;
    const cutoff = options?.stopAtEdited
      ? sendablePrefixLength(queued, get().editingByTaskId[taskId])
      : queued.length;
    if (cutoff === 0) return EMPTY;
    const drained = queued.slice(0, cutoff);
    const rest = queued.slice(cutoff);
    set((state) => {
      if (rest.length === 0) {
        const { [taskId]: _drained, ...others } = state.queuesByTaskId;
        return { queuesByTaskId: others };
      }
      return {
        queuesByTaskId: { ...state.queuesByTaskId, [taskId]: rest },
      };
    });
    return drained;
  },
  prepend: (taskId, messages) =>
    set((state) => ({
      queuesByTaskId: {
        ...state.queuesByTaskId,
        [taskId]: [...messages, ...(state.queuesByTaskId[taskId] ?? [])],
      },
    })),
  remove: (taskId, messageId) =>
    set((state) => {
      const queue = state.queuesByTaskId[taskId];
      if (!queue) return state;
      const next = queue.filter((m) => m.id !== messageId);
      if (next.length === queue.length) return state;
      const editingByTaskId =
        state.editingByTaskId[taskId] === messageId
          ? omit(state.editingByTaskId, taskId)
          : state.editingByTaskId;
      if (next.length === 0) {
        const { [taskId]: _emptied, ...rest } = state.queuesByTaskId;
        return { queuesByTaskId: rest, editingByTaskId };
      }
      return {
        queuesByTaskId: { ...state.queuesByTaskId, [taskId]: next },
        editingByTaskId,
      };
    }),
  move: (taskId, messageId, direction) =>
    set((state) => {
      const queue = state.queuesByTaskId[taskId];
      if (!queue) return state;
      const from = queue.findIndex((m) => m.id === messageId);
      if (from === -1) return state;
      const to = direction === "up" ? from - 1 : from + 1;
      if (to < 0 || to >= queue.length) return state;
      const next = [...queue];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return {
        queuesByTaskId: { ...state.queuesByTaskId, [taskId]: next },
      };
    }),
  update: (taskId, messageId, patch) =>
    set((state) => {
      const queue = state.queuesByTaskId[taskId];
      if (!queue?.some((m) => m.id === messageId)) return state;
      const next = queue.map((m) =>
        m.id === messageId
          ? { ...m, content: patch.content, attachments: patch.attachments }
          : m,
      );
      return {
        queuesByTaskId: { ...state.queuesByTaskId, [taskId]: next },
      };
    }),
  setEditing: (taskId, messageId) =>
    set((state) => ({
      editingByTaskId: { ...state.editingByTaskId, [taskId]: messageId },
    })),
  clearEditing: (taskId) =>
    set((state) =>
      taskId in state.editingByTaskId
        ? { editingByTaskId: omit(state.editingByTaskId, taskId) }
        : state,
    ),
  getQueue: (taskId) => get().queuesByTaskId[taskId] ?? EMPTY,
}));

function omit<T extends Record<string, string>>(
  record: T,
  key: string,
): Record<string, string> {
  const { [key]: _removed, ...rest } = record;
  return rest;
}

/**
 * Combine buffered messages into a single prompt, preserving the order they
 * were typed: texts join with a blank line, attachments concatenate.
 */
export function combineQueuedMessages(messages: QueuedMessage[]): {
  text: string;
  attachments: PendingAttachment[];
} {
  return {
    text: messages.map((m) => m.content).join("\n\n"),
    attachments: messages.flatMap((m) => m.attachments),
  };
}
