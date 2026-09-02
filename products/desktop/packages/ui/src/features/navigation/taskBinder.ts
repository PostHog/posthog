import type { Task } from "@posthog/shared/domain-types";

export interface EnsureWorkspaceResult {
  staleFolderId?: string;
}

export interface NavigationTaskBinder {
  ensureWorkspaceForTask(
    task: Task,
  ): Promise<EnsureWorkspaceResult | undefined>;
}

export const NAVIGATION_TASK_BINDER = Symbol.for(
  "posthog.ui.NavigationTaskBinder",
);
