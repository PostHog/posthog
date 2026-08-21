import type { CloudRegion } from "@posthog/shared";

/**
 * Host-side cross-feature coordination triggered by auth mutations (query-cache
 * invalidation, navigation, onboarding/session resets, analytics). These live
 * outside packages/ui because they reach other app features; the desktop binds
 * an adapter. Move each effect into the owning feature's contribution as those
 * features migrate, then shrink this port.
 */
export interface IAuthSideEffects {
  onAuthSuccess(region: CloudRegion, projectId: number | null): void;
  beforeProjectSwitch(): void;
  onProjectSelected(): void;
  onLogout(previousRegion: CloudRegion | null): void;
}

export const AUTH_SIDE_EFFECTS = Symbol.for("posthog.ui.auth.sideEffects");
