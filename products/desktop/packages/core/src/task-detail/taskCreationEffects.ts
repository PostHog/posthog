import type { TaskCreationInput, TaskCreationOutput } from "@posthog/shared";

/**
 * Host-side reactions to a successful task-creation: optimistic workspace
 * query-cache update, cache invalidation, and the cross-store "last used"
 * settings + draft clearing. The renderer adapter wires these to React-Query
 * and the zustand stores; core stays free of both.
 */
export interface TaskCreationEffects {
  onWorkspaceCreated(output: TaskCreationOutput): void;
  onCreateSuccess(output: TaskCreationOutput, input?: TaskCreationInput): void;
}
