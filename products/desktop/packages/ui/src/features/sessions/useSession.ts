import type {
  AvailableCommand,
  SessionConfigOption,
} from "@agentclientprotocol/sdk";
import {
  extractAvailableCommandsFromEvents,
  extractUserPromptsFromEvents,
} from "@posthog/core/sessions/sessionEvents";
import type { PermissionRequest } from "@posthog/ui/features/sessions/sessionLogTypes";
import { shallow } from "zustand/shallow";
import {
  type Adapter,
  type AgentSession,
  getConfigOptionByCategory,
  type OptimisticItem,
  type QueuedMessage,
  useSessionStore,
} from "./sessionStore";

export const useSessions = () => useSessionStore((s) => s.sessions);

/** O(1) lookup using taskIdIndex */
export const useSessionForTask = (
  taskId: string | undefined,
): AgentSession | undefined =>
  useSessionStore((s) => {
    if (!taskId) return undefined;
    const taskRunId = s.taskIdIndex[taskId];
    if (!taskRunId) return undefined;
    return s.sessions[taskRunId];
  });

/**
 * Select a derived value from a task's session with referential stability.
 *
 * Prefer this over {@link useSessionForTask} whenever a component needs only a
 * field or two: `useSessionForTask` returns the whole session object, whose
 * identity changes on every streamed event (the store appends to `events` via
 * immer), so every consumer re-renders ~60fps for the length of a turn. This
 * selector re-renders only when the projected value actually changes. Pass
 * `shallow` as `equality` when the projection returns an object or array.
 */
export function useSessionSelector<T>(
  taskId: string | undefined,
  select: (session: AgentSession | undefined) => T,
  equality?: (a: T, b: T) => boolean,
): T {
  return useSessionStore((s) => {
    const taskRunId = taskId ? s.taskIdIndex[taskId] : undefined;
    return select(taskRunId ? s.sessions[taskRunId] : undefined);
  }, equality);
}

/**
 * Returns `null` when the agent hasn't sent an `available_commands_update` yet,
 * so callers can distinguish that from an explicit empty list.
 */
export function getAvailableCommandsForTask(
  taskId: string | undefined,
): AvailableCommand[] | null {
  if (!taskId) return null;
  const state = useSessionStore.getState();
  const taskRunId = state.taskIdIndex[taskId];
  if (!taskRunId) return null;
  const session = state.sessions[taskRunId];
  if (!session?.events) return null;
  return extractAvailableCommandsFromEvents(session.events);
}

export function getUserPromptsForTask(taskId: string | undefined): string[] {
  if (!taskId) return [];
  const state = useSessionStore.getState();
  const taskRunId = state.taskIdIndex[taskId];
  if (!taskRunId) return [];
  const session = state.sessions[taskRunId];
  if (!session?.events) return [];
  return extractUserPromptsFromEvents(session.events);
}

export const usePendingPermissionsForTask = (
  taskId: string | undefined,
): Map<string, PermissionRequest> => {
  return useSessionStore((s) => {
    if (!taskId) return new Map();
    const taskRunId = s.taskIdIndex[taskId];
    if (!taskRunId) return new Map();
    const session = s.sessions[taskRunId];
    return session?.pendingPermissions ?? new Map();
  }, shallow);
};

export function getPendingPermissionsForTask(
  taskId: string | undefined,
): Map<string, PermissionRequest> {
  if (!taskId) return new Map();
  const state = useSessionStore.getState();
  const taskRunId = state.taskIdIndex[taskId];
  if (!taskRunId) return new Map();
  const session = state.sessions[taskRunId];
  return session?.pendingPermissions ?? new Map();
}

export const useQueuedMessagesForTask = (
  taskId: string | undefined,
): QueuedMessage[] => {
  return useSessionStore((s) => {
    if (!taskId) return [];
    const taskRunId = s.taskIdIndex[taskId];
    if (!taskRunId) return [];
    const session = s.sessions[taskRunId];
    return session?.messageQueue ?? [];
  }, shallow);
};

export const useOptimisticItemsForTask = (
  taskId: string | undefined,
): OptimisticItem[] => {
  return useSessionStore((s) => {
    if (!taskId) return [];
    const taskRunId = s.taskIdIndex[taskId];
    if (!taskRunId) return [];
    return s.sessions[taskRunId]?.optimisticItems ?? [];
  }, shallow);
};

// --- Config Option Hooks ---

/** Get a config option by category for a task */
export const useConfigOptionForTask = (
  taskId: string | undefined,
  category: string,
): SessionConfigOption | undefined => {
  return useSessionStore((s) => {
    if (!taskId) return undefined;
    const taskRunId = s.taskIdIndex[taskId];
    if (!taskRunId) return undefined;
    const session = s.sessions[taskRunId];
    return getConfigOptionByCategory(session?.configOptions, category);
  });
};

/** Get the mode config option for a task */
export const useModeConfigOptionForTask = (
  taskId: string | undefined,
): SessionConfigOption | undefined => {
  return useConfigOptionForTask(taskId, "mode");
};

/** Get the model config option for a task */
export const useModelConfigOptionForTask = (
  taskId: string | undefined,
): SessionConfigOption | undefined => {
  return useConfigOptionForTask(taskId, "model");
};

/** Get the thought level config option for a task */
export const useThoughtLevelConfigOptionForTask = (
  taskId: string | undefined,
): SessionConfigOption | undefined => {
  return useConfigOptionForTask(taskId, "thought_level");
};

/** Get the adapter type for a task */
export const useAdapterForTask = (
  taskId: string | undefined,
): Adapter | undefined => {
  return useSessionStore((s) => {
    if (!taskId) return undefined;
    const taskRunId = s.taskIdIndex[taskId];
    if (!taskRunId) return undefined;
    return s.sessions[taskRunId]?.adapter;
  });
};

/**
 * Whether a task's session is a cloud run. A primitive selector, so consumers
 * that only need this flag don't re-render on every streamed event the way
 * reading the whole session via {@link useSessionForTask} would.
 */
export const useSessionIsCloud = (taskId: string | undefined): boolean => {
  return useSessionStore((s) => {
    if (!taskId) return false;
    const taskRunId = s.taskIdIndex[taskId];
    if (!taskRunId) return false;
    return s.sessions[taskRunId]?.isCloud ?? false;
  });
};

/** Whether a cloud handoff is in progress for a task. Primitive selector — see
 * {@link useSessionIsCloud}. */
export const useSessionHandoffInProgress = (
  taskId: string | undefined,
): boolean => {
  return useSessionStore((s) => {
    if (!taskId) return false;
    const taskRunId = s.taskIdIndex[taskId];
    if (!taskRunId) return false;
    return s.sessions[taskRunId]?.handoffInProgress ?? false;
  });
};
