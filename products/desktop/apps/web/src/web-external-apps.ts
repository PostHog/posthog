import type {
  ExternalAppsFocusCoordinator,
  ExternalAppsWorkspaceClient,
} from "@posthog/core/external-apps/identifiers";

// External apps (open in a local editor, reveal in Finder, copy a local path)
// are inherently local-filesystem features. The cloud-only web host has none,
// so these stubs report "no apps" and no-op. The real ExternalAppService
// (bound via externalAppsCoreModule) is still resolved — it's the sidebar's
// eager useExternalAppAction dependency — it just never has anything to open.
export const webExternalAppsWorkspaceClient: ExternalAppsWorkspaceClient = {
  openInApp: () =>
    Promise.resolve({
      success: false,
      error: "Opening in a local app is not available on the web",
    }),
  setLastUsed: () => Promise.resolve(),
  getDetectedApps: () => Promise.resolve([]),
  copyPath: () => Promise.resolve(),
};

export const webExternalAppsFocusCoordinator: ExternalAppsFocusCoordinator = {
  getSession: () => null,
  // Focus mode operates on a local worktree; it can never be enabled on web
  // (workspace mode is cloud-only), so this is never reached.
  enableFocus: () =>
    Promise.reject(new Error("Focus mode is not available on the web")),
};
