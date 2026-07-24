import type { WorkspaceClient } from "@posthog/workspace-client/client";
import type { FocusSession } from "./identifiers";

export const FOCUS_WORKSPACE_CLIENT = Symbol.for(
  "posthog.core.focusWorkspaceClient",
);
export const FOCUS_SESSION_STORE = Symbol.for("posthog.core.focusSessionStore");
export const FOCUS_WORKTREE_PATHS = Symbol.for(
  "posthog.core.focusWorktreePaths",
);

export interface FocusWorkspaceClient {
  focus: WorkspaceClient["focus"];
}

export interface FocusSessionStore {
  getSession(mainRepoPath: string): FocusSession | null;
  saveSession(session: FocusSession): void;
  deleteSession(mainRepoPath: string): void;
}

export interface FocusWorktreePaths {
  toRelativeWorktreePath(absolutePath: string, mainRepoPath: string): string;
  toAbsoluteWorktreePath(relativePath: string): string;
  worktreeExistsAtPath(relativePath: string): Promise<boolean>;
}
