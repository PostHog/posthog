import type { CloudRegion } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import {
  clearAuthScopedQueries,
  refreshAuthStateQuery,
} from "@posthog/ui/features/auth/authQueries";
import { useAuthUiStateStore } from "@posthog/ui/features/auth/authUiStateStore";
import type { IAuthSideEffects } from "@posthog/ui/features/auth/identifiers";
import { useOnboardingStore } from "@posthog/ui/features/onboarding/onboardingStore";
import { resetSessionService } from "@posthog/ui/features/sessions/sessionServiceHost";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { injectable } from "inversify";

@injectable()
export class RendererAuthSideEffects implements IAuthSideEffects {
  onAuthSuccess(region: CloudRegion, projectId: number | null): void {
    void refreshAuthStateQuery();
    useAuthUiStateStore.getState().clearStaleRegion();
    track(ANALYTICS_EVENTS.USER_LOGGED_IN, {
      project_id: projectId?.toString() ?? "",
      region,
    });
  }

  beforeProjectSwitch(): void {
    resetSessionService();
  }

  onProjectSelected(): void {
    clearAuthScopedQueries();
    void refreshAuthStateQuery();
    openTaskInput();
  }

  onLogout(previousRegion: CloudRegion | null): void {
    track(ANALYTICS_EVENTS.USER_LOGGED_OUT);
    resetSessionService();
    clearAuthScopedQueries();
    if (previousRegion) {
      useAuthUiStateStore.getState().setStaleRegion(previousRegion);
    }
    openTaskInput();
    useOnboardingStore.getState().resetSelections();
  }
}
