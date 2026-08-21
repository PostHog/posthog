import type {
  ContentBlock,
  SessionConfigOption,
} from "@agentclientprotocol/sdk";
import {
  type SessionState,
  sessionStore,
  sessionStoreSetters,
} from "@posthog/core/sessions/sessionStore";
import {
  type Adapter,
  type AgentSession,
  cycleModeOption,
  type ExecutionMode,
  flattenSelectOptions,
  getConfigOptionByCategory,
  getCurrentModeFromConfigOptions,
  isSelectGroup,
  mergeConfigOptions,
  type OptimisticItem,
  type PermissionRequest,
  type QueuedMessage,
  type SessionStatus,
  type TaskRunStatus,
} from "@posthog/shared";
import { useStore } from "zustand";

// --- Type re-exports ---

export type {
  Adapter,
  AgentSession,
  ExecutionMode,
  OptimisticItem,
  PermissionRequest,
  QueuedMessage,
  SessionConfigOption,
  SessionStatus,
  TaskRunStatus,
};
export type { ContentBlock };
export type { SessionState };
export {
  cycleModeOption,
  flattenSelectOptions,
  getConfigOptionByCategory,
  getCurrentModeFromConfigOptions,
  isSelectGroup,
  mergeConfigOptions,
};

// --- Setter re-export ---

export { sessionStoreSetters };

// --- React hook backed by the core vanilla store ---

function useSessionStoreHook<T>(
  selector: (s: SessionState) => T,
  equalityFn?: (a: T, b: T) => boolean,
): T {
  return useStore(sessionStore, selector, equalityFn);
}

export const useSessionStore: typeof useSessionStoreHook & {
  getState: typeof sessionStore.getState;
  setState: typeof sessionStore.setState;
  subscribe: typeof sessionStore.subscribe;
} = Object.assign(useSessionStoreHook, {
  getState: () => sessionStore.getState(),
  setState: sessionStore.setState.bind(sessionStore),
  subscribe: sessionStore.subscribe.bind(sessionStore),
});

// --- Re-exports ---

export {
  getAvailableCommandsForTask,
  getPendingPermissionsForTask,
  getUserPromptsForTask,
  useAdapterForTask,
  useConfigOptionForTask,
  useModeConfigOptionForTask,
  useModelConfigOptionForTask,
  useOptimisticItemsForTask,
  usePendingPermissionsForTask,
  useQueuedMessagesForTask,
  useSessionForTask,
  useSessionHandoffInProgress,
  useSessionIsCloud,
  useSessionSelector,
  useSessions,
  useThoughtLevelConfigOptionForTask,
} from "./useSession";
