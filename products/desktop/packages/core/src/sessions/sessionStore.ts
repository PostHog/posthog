import type { ContentBlock } from "@agentclientprotocol/sdk";
import {
  type AcpMessage,
  type AgentSession,
  type OptimisticItem,
  type PermissionRequest,
  type QueuedMessage,
  sendableQueuePrefixLength,
  type TaskRunStatus,
} from "@posthog/shared";
import { isTerminalStatus } from "@posthog/shared/domain-types";
import { setAutoFreeze } from "immer";
import { immer } from "zustand/middleware/immer";
import { createStore } from "zustand/vanilla";

// immer autofreeze deep-walks produced state on every commit. For the
// append-only `events` array that re-walks the whole (growing) array on every
// streamed event — O(n) per append, O(n²) per turn. Autofreeze is a dev-time
// mutation guard with no runtime value, so disable it; events are frozen
// individually at the append/creation seam instead, which is O(1) each.
setAutoFreeze(false);

export interface SessionState {
  /** Sessions indexed by taskRunId */
  sessions: Record<string, AgentSession>;
  /** Index mapping taskId -> taskRunId for O(1) lookups */
  taskIdIndex: Record<string, string>;
}

export const sessionStore = createStore<SessionState>()(
  immer(() => ({
    sessions: {},
    taskIdIndex: {},
  })),
);

/**
 * How many messages to drain off the head of a queue, honoring both options:
 * `stopAtEdited` caps at the in-place edit boundary (nothing from the message
 * being edited onward); `max` caps the count. The turn-end auto-drain passes
 * `max: 1` so queued messages send one turn at a time instead of merged into
 * one prompt; cancel/recall pass neither and take the whole queue.
 */
function drainCutoff(
  session: AgentSession,
  options?: { stopAtEdited?: boolean; max?: number },
): number {
  const sendable = options?.stopAtEdited
    ? sendableQueuePrefixLength(session)
    : session.messageQueue.length;
  return options?.max != null ? Math.min(sendable, options.max) : sendable;
}

/**
 * Drain messages off the head of the queue, honoring {@link drainCutoff}.
 * Reads the queue from the frozen committed state BEFORE entering the immer
 * draft, otherwise the returned items are proxies that get revoked when
 * setState exits and any later access throws "Cannot perform 'get' on a proxy
 * that has been revoked".
 */
function drainQueueHead(
  taskId: string,
  options?: { stopAtEdited?: boolean; max?: number },
): QueuedMessage[] {
  const state = sessionStore.getState();
  const taskRunId = state.taskIdIndex[taskId];
  if (!taskRunId) return [];
  const session = state.sessions[taskRunId];
  if (!session || session.messageQueue.length === 0) return [];

  const cutoff = drainCutoff(session, options);
  if (cutoff === 0) return [];

  const drained = session.messageQueue.slice(0, cutoff);
  sessionStore.setState((draft) => {
    const trid = draft.taskIdIndex[taskId];
    if (!trid) return;
    const draftSession = draft.sessions[trid];
    if (draftSession) {
      draftSession.messageQueue = draftSession.messageQueue.slice(cutoff);
    }
  });
  return drained;
}

export const sessionStoreSetters = {
  setSession: (session: AgentSession) => {
    sessionStore.setState((state) => {
      // Clean up old session if taskId already has a different taskRunId
      const existingTaskRunId = state.taskIdIndex[session.taskId];
      if (existingTaskRunId && existingTaskRunId !== session.taskRunId) {
        delete state.sessions[existingTaskRunId];
      }

      state.sessions[session.taskRunId] = session;
      state.taskIdIndex[session.taskId] = session.taskRunId;
    });
  },

  removeSession: (taskRunId: string) => {
    sessionStore.setState((state) => {
      const session = state.sessions[taskRunId];
      if (session) {
        delete state.taskIdIndex[session.taskId];
      }
      delete state.sessions[taskRunId];
    });
  },

  updateSession: (taskRunId: string, updates: Partial<AgentSession>) => {
    sessionStore.setState((state) => {
      if (state.sessions[taskRunId]) {
        Object.assign(state.sessions[taskRunId], updates);
      }
    });
  },

  appendEvents: (
    taskRunId: string,
    events: AcpMessage[],
    newLineCount?: number,
  ) => {
    sessionStore.setState((state) => {
      const session = state.sessions[taskRunId];
      if (session) {
        // Keep each event immutable once stored (O(1) each). The store disables
        // immer autofreeze, so this is the only freeze.
        for (const event of events) Object.freeze(event);
        session.events.push(...events);
        if (newLineCount !== undefined) {
          session.processedLineCount = newLineCount;
        }
      }
    });
  },

  /**
   * Free a backgrounded session's transcript to reclaim memory. The events are
   * reloaded from disk the next time the session is viewed (see
   * `SessionService.ensureEventsLoaded`). No-op if the session is gone.
   */
  evictEvents: (taskRunId: string) => {
    sessionStore.setState((state) => {
      const session = state.sessions[taskRunId];
      if (session && session.events.length > 0) {
        session.events = [];
        session.processedLineCount = 0;
      }
    });
  },

  /**
   * Replace a session's transcript in place (rehydration after eviction),
   * preserving its live status/config. No-op if the session is gone.
   */
  restoreEvents: (
    taskRunId: string,
    events: AcpMessage[],
    lineCount: number,
  ) => {
    sessionStore.setState((state) => {
      const session = state.sessions[taskRunId];
      if (session) {
        for (const event of events) Object.freeze(event);
        session.events = events;
        session.processedLineCount = lineCount;
      }
    });
  },

  updateCloudStatus: (
    taskRunId: string,
    fields: {
      status?: TaskRunStatus;
      stage?: string | null;
      output?: Record<string, unknown> | null;
      errorMessage?: string | null;
      branch?: string | null;
    },
  ) => {
    sessionStore.setState((state) => {
      const session = state.sessions[taskRunId];
      if (!session) return;
      if (fields.status !== undefined) {
        const currentStatus = session.cloudStatus;
        if (
          isTerminalStatus(currentStatus) &&
          !isTerminalStatus(fields.status)
        ) {
          return;
        }
        session.cloudStatus = fields.status;
      }
      if (fields.stage !== undefined) session.cloudStage = fields.stage;
      if (fields.output !== undefined) session.cloudOutput = fields.output;
      if (fields.errorMessage !== undefined)
        session.cloudErrorMessage = fields.errorMessage;
      if (fields.branch !== undefined) session.cloudBranch = fields.branch;
    });
  },

  setPendingPermissions: (
    taskRunId: string,
    permissions: Map<string, PermissionRequest>,
  ) => {
    sessionStore.setState((state) => {
      if (state.sessions[taskRunId]) {
        state.sessions[taskRunId].pendingPermissions = permissions;
      }
    });
  },

  enqueueMessage: (
    taskId: string,
    content: string,
    rawPrompt?: string | ContentBlock[],
  ) => {
    const id = `queue-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
    sessionStore.setState((state) => {
      const taskRunId = state.taskIdIndex[taskId];
      if (!taskRunId) return;

      const session = state.sessions[taskRunId];
      if (session) {
        session.messageQueue.push({
          id,
          content,
          rawPrompt,
          queuedAt: Date.now(),
        });
      }
    });
  },

  removeQueuedMessage: (taskId: string, messageId: string) => {
    sessionStore.setState((state) => {
      const taskRunId = state.taskIdIndex[taskId];
      if (!taskRunId) return;
      const session = state.sessions[taskRunId];
      if (session) {
        session.messageQueue = session.messageQueue.filter(
          (msg) => msg.id !== messageId,
        );
      }
    });
  },

  clearMessageQueue: (taskId: string) => {
    sessionStore.setState((state) => {
      const taskRunId = state.taskIdIndex[taskId];
      if (!taskRunId) return;

      const session = state.sessions[taskRunId];
      if (session) {
        session.messageQueue = [];
      }
    });
  },

  /**
   * Move a queued message to a new position, preserving its identity. Used by
   * the drag-to-reorder affordance: the queue drains in array order, so the
   * order the user sees is the order the messages send.
   */
  moveQueuedMessage: (taskId: string, fromIndex: number, toIndex: number) => {
    sessionStore.setState((state) => {
      const taskRunId = state.taskIdIndex[taskId];
      if (!taskRunId) return;
      const session = state.sessions[taskRunId];
      if (!session) return;
      const queue = session.messageQueue;
      if (
        fromIndex < 0 ||
        toIndex < 0 ||
        fromIndex >= queue.length ||
        toIndex >= queue.length ||
        fromIndex === toIndex
      ) {
        return;
      }
      const [moved] = queue.splice(fromIndex, 1);
      if (moved) queue.splice(toIndex, 0, moved);
    });
  },

  /**
   * Replace a queued message's content in place, keeping its id, position, and
   * queue timestamp. Used by edit-in-place: the message is edited in the
   * composer and re-serialized here without leaving the queue.
   */
  updateQueuedMessage: (
    taskId: string,
    messageId: string,
    patch: { content: string; rawPrompt?: string | ContentBlock[] },
  ) => {
    sessionStore.setState((state) => {
      const taskRunId = state.taskIdIndex[taskId];
      if (!taskRunId) return;
      const session = state.sessions[taskRunId];
      if (!session) return;
      const message = session.messageQueue.find((m) => m.id === messageId);
      if (!message) return;
      message.content = patch.content;
      message.rawPrompt = patch.rawPrompt;
    });
  },

  /**
   * Mark a queued message as being edited in the composer. While set it holds
   * back the auto-drain: the message and everything after it stay queued (only
   * the messages before it may send) until the edit is saved or cancelled.
   */
  setEditingQueuedMessage: (taskId: string, messageId: string) => {
    sessionStore.setState((state) => {
      const taskRunId = state.taskIdIndex[taskId];
      if (!taskRunId) return;
      const session = state.sessions[taskRunId];
      if (session) session.editingQueuedId = messageId;
    });
  },

  /** Release the in-place edit hold set by {@link setEditingQueuedMessage}. */
  clearEditingQueuedMessage: (taskId: string) => {
    sessionStore.setState((state) => {
      const taskRunId = state.taskIdIndex[taskId];
      if (!taskRunId) return;
      const session = state.sessions[taskRunId];
      if (session) session.editingQueuedId = undefined;
    });
  },

  /**
   * Drain messages off the head of the queue as one combined string. See
   * {@link drainCutoff} for the `stopAtEdited`/`max` semantics; cancel/recall
   * pass no options and pull the whole queue back into the composer.
   */
  dequeueMessagesAsText: (
    taskId: string,
    options?: { stopAtEdited?: boolean; max?: number },
  ): string | null => {
    const drained = drainQueueHead(taskId, options);
    if (drained.length === 0) return null;
    return drained.map((msg) => msg.content).join("\n\n");
  },

  /**
   * Drain messages off the head of the queue as raw messages. See
   * {@link dequeueMessagesAsText} for the `stopAtEdited`/`max` semantics.
   */
  dequeueMessages: (
    taskId: string,
    options?: { stopAtEdited?: boolean; max?: number },
  ): QueuedMessage[] => drainQueueHead(taskId, options),

  /**
   * Splice messages back at the head of the queue. Used to roll back a
   * dispatch attempt that drained the queue but failed before delivery.
   */
  prependQueuedMessages: (taskId: string, messages: QueuedMessage[]) => {
    if (messages.length === 0) return;
    sessionStore.setState((state) => {
      const taskRunId = state.taskIdIndex[taskId];
      if (!taskRunId) return;
      const session = state.sessions[taskRunId];
      if (!session) return;
      session.messageQueue = [...messages, ...session.messageQueue];
    });
  },

  appendOptimisticItem: (
    taskRunId: string,
    item: OptimisticItem extends infer T
      ? T extends { id: string }
        ? Omit<T, "id">
        : never
      : never,
  ): void => {
    const id = `optimistic-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
    sessionStore.setState((state) => {
      const session = state.sessions[taskRunId];
      if (session) {
        session.optimisticItems.push({ ...item, id } as OptimisticItem);
      }
    });
  },

  clearOptimisticItems: (taskRunId: string): void => {
    sessionStore.setState((state) => {
      const session = state.sessions[taskRunId];
      if (session) {
        session.optimisticItems = [];
      }
    });
  },

  clearTailOptimisticItems: (taskRunId: string): void => {
    sessionStore.setState((state) => {
      const session = state.sessions[taskRunId];
      if (session) {
        session.optimisticItems = session.optimisticItems.filter(
          (item) => item.type !== "user_message" || item.pinToTop !== false,
        );
      }
    });
  },

  replaceOptimisticWithEvent: (taskRunId: string, event: AcpMessage): void => {
    sessionStore.setState((state) => {
      const session = state.sessions[taskRunId];
      if (session) {
        session.events.push(Object.freeze(event));
        session.optimisticItems = [];
      }
    });
  },

  /** O(1) lookup using taskIdIndex */
  getSessionByTaskId: (taskId: string): AgentSession | undefined => {
    const state = sessionStore.getState();
    const taskRunId = state.taskIdIndex[taskId];
    if (!taskRunId) return undefined;
    return state.sessions[taskRunId];
  },

  getSessions: (): Record<string, AgentSession> => {
    return sessionStore.getState().sessions;
  },

  clearAll: () => {
    sessionStore.setState((state) => {
      state.sessions = {};
      state.taskIdIndex = {};
    });
  },
};
