import type { DetectedRepoFullName } from "./repoMismatch";

export const WORKSPACE_SETUP_SERVICE = Symbol.for(
  "posthog.core.workspace.setupService",
);
export const WORKSPACE_SETUP_GIT_CLIENT = Symbol.for(
  "posthog.core.workspace.setupGitClient",
);

export interface WorkspaceSetupGitClient {
  detectRepo(args: {
    directoryPath: string;
  }): Promise<DetectedRepoFullName | null>;
}
