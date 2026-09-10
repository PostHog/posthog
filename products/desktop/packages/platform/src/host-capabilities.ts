/**
 * Coarse host capabilities the shared UI branches on. Kept deliberately small:
 * a capability belongs here only when the UI must render differently by host
 * (not merely bind a different adapter). Hosts bind a constant value.
 */
export interface HostCapabilities {
  /**
   * Whether the host can access the local filesystem — local repository
   * folders, git worktrees, and a terminal. Desktop (Electron) has it; the
   * cloud-only browser host does not, so the UI falls back to remote
   * (connected-GitHub-org) repositories and cloud workspaces.
   */
  readonly localWorkspaces: boolean;

  /**
   * Whether the host can hold a custom PostHog instance: the sign-in screen
   * offers the Custom region, and the host serves the `customCloud` routes.
   * Desktop (Electron) has it; the browser host has no store for it.
   */
  readonly customCloud: boolean;

  /** Whether the host serves the vendored sketchpad module pipeline. */
  readonly vendoredSketchpadModules: boolean;
}

export const HOST_CAPABILITIES = Symbol.for(
  "posthog.platform.hostCapabilities",
);
