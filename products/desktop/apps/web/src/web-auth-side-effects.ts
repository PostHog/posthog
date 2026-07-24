import type { CloudRegion } from "@posthog/shared";
import {
  clearAuthScopedQueries,
  refreshAuthStateQuery,
} from "@posthog/ui/features/auth/authQueries";
import { useAuthUiStateStore } from "@posthog/ui/features/auth/authUiStateStore";
import type { IAuthSideEffects } from "@posthog/ui/features/auth/identifiers";
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
    openTaskInput();
  }

  onLogout(previousRegion: CloudRegion | null): void {
    clearAuthScopedQueries();
    if (previousRegion) {
      useAuthUiStateStore.getState().setStaleRegion(previousRegion);
    }
    openTaskInput();
    useOnboardingStore.getState().resetSelections();
  }
}
