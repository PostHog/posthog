import {
  type SessionState,
  sessionStore,
  sessionStoreSetters,
} from "@posthog/core/sessions/sessionStore";
import {
  type Adapter,
  type AgentSession,
  cycleModeOption,
  flattenSelectOptions,
  getConfigOptionByCategory,
  getCurrentModeFromConfigOptions,
  type OptimisticItem,
  type QueuedMessage,
} from "@posthog/shared";
import { useStore } from "zustand";

// --- Type re-exports ---

export type { Adapter, AgentSession, OptimisticItem, QueuedMessage };
export {
  cycleModeOption,
  flattenSelectOptions,
  getConfigOptionByCategory,
  getCurrentModeFromConfigOptions,
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
  useAdapterForTask,
  useConfigOptionForTask,
  useModeConfigOptionForTask,
  useModelConfigOptionForTask,
  useOptimisticItemsForTask,
  usePendingPermissionsForTask,
  useQueuedMessagesForTask,
  useSessionForTask,
  useSessionIsCloud,
  useSessionSelector,
  useThoughtLevelConfigOptionForTask,
} from "./useSession";
