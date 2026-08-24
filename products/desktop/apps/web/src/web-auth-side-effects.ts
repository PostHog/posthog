import type { CloudRegion } from "@posthog/shared";
import {
  clearAuthScopedQueries,
  refreshAuthStateQuery,
} from "@posthog/ui/features/auth/authQueries";
import { useAuthUiStateStore } from "@posthog/ui/features/auth/authUiStateStore";
import type { IAuthSideEffects } from "@posthog/ui/features/auth/identifiers";
import { resetCurrentChannel } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { useOnboardingStore } from "@posthog/ui/features/onboarding/onboardingStore";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { injectable } from "inversify";

// Web counterpart of the desktop RendererAuthSideEffects. Identical store/query
// coordination, minus the desktop SessionService reset — web cloud sessions are
// owned by the core SessionService, not a renderer singleton.
@injectable()
export class WebAuthSideEffects implements IAuthSideEffects {
  onAuthSuccess(_region: CloudRegion, _projectId: number | null): void {
    void refreshAuthStateQuery();
    useAuthUiStateStore.getState().clearStaleRegion();
  }

  beforeProjectSwitch(): void {}

  onProjectSelected(): void {
    clearAuthScopedQueries();
    void refreshAuthStateQuery();
    // Before openTaskInput, which files a new task into the scoped channel —
    // a channel id from the project we just left.
    resetCurrentChannel();
    openTaskInput();
  }

  onLogout(previousRegion: CloudRegion | null): void {
    clearAuthScopedQueries();
    if (previousRegion) {
      useAuthUiStateStore.getState().setStaleRegion(previousRegion);
    }
    resetCurrentChannel();
    openTaskInput();
    useOnboardingStore.getState().resetSelections();
  }
}
