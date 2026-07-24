import type { ISetupStore } from "@posthog/core/setup/identifiers";
import type { ActivityEntry } from "@posthog/core/setup/setupState";
import type { DiscoveredTask } from "@posthog/core/setup/types";
import {
  selectRepoDiscovery,
  selectRepoEnricher,
  useSetupStore,
} from "@posthog/ui/features/setup/setupStore";

/**
 * Host delegate exposing the setup zustand store to the core
 * `SetupRunService`. Inverts the store coupling (the connectivity getValue()
 * pattern): core writes UI state through this narrow interface instead of
 * importing `@posthog/ui`.
 */
export const setupStore: ISetupStore = {
  getDiscoveryStatus: (repoPath) =>
    selectRepoDiscovery(useSetupStore.getState(), repoPath).status,
  getEnricherStatus: (repoPath) =>
    selectRepoEnricher(useSetupStore.getState(), repoPath).status,
  anyDiscoveryStarted: () =>
    Object.values(useSetupStore.getState().discoveryByRepo).some(
      (d) => d.status !== "idle",
    ),
  startDiscovery: (repoPath, taskId, taskRunId) =>
    useSetupStore.getState().startDiscovery(repoPath, taskId, taskRunId),
  completeDiscovery: (repoPath, tasks: DiscoveredTask[]) =>
    useSetupStore.getState().completeDiscovery(repoPath, tasks),
  failDiscovery: (repoPath, message) =>
    useSetupStore.getState().failDiscovery(repoPath, message),
  pushDiscoveryActivity: (repoPath, entry: ActivityEntry) =>
    useSetupStore.getState().pushDiscoveryActivity(repoPath, entry),
  startEnrichment: (repoPath) =>
    useSetupStore.getState().startEnrichment(repoPath),
  completeEnrichment: (repoPath) =>
    useSetupStore.getState().completeEnrichment(repoPath),
  failEnrichment: (repoPath) =>
    useSetupStore.getState().failEnrichment(repoPath),
  addEnricherSuggestionIfMissing: (task: DiscoveredTask) =>
    useSetupStore.getState().addEnricherSuggestionIfMissing(task),
};
