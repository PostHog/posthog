import type { CloudRegion } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import {
  clearAuthScopedQueries,
  refreshAuthStateQuery,
} from "@posthog/ui/features/auth/authQueries";
import { useAuthUiStateStore } from "@posthog/ui/features/auth/authUiStateStore";
import type { IAuthSideEffects } from "@posthog/ui/features/auth/identifiers";
import {
  BROWSER_TABS_CLIENT,
  type BrowserTabsClient,
} from "@posthog/ui/features/browser-tabs/browserTabsClient";
import { resetCurrentChannel } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { useOnboardingStore } from "@posthog/ui/features/onboarding/onboardingStore";
import { resetSessionService } from "@posthog/ui/features/sessions/sessionServiceHost";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { inject, injectable } from "inversify";

@injectable()
export class RendererAuthSideEffects implements IAuthSideEffects {
  constructor(
    @inject(BROWSER_TABS_CLIENT)
    private readonly browserTabsClient: BrowserTabsClient,
  ) {}

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

  async onProjectSelected(): Promise<void> {
    clearAuthScopedQueries();
    // Before openTaskInput, which files a new task into the scoped channel —
    // a channel id from the project we just left.
    resetCurrentChannel();
    await Promise.all([
      refreshAuthStateQuery(),
      this.browserTabsClient.reset(),
    ]);
    openTaskInput();
  }

  async onLogout(previousRegion: CloudRegion | null): Promise<void> {
    track(ANALYTICS_EVENTS.USER_LOGGED_OUT);
    resetSessionService();
    clearAuthScopedQueries();
    if (previousRegion) {
      useAuthUiStateStore.getState().setStaleRegion(previousRegion);
    }
    resetCurrentChannel();
    await this.browserTabsClient.reset();
    openTaskInput();
    useOnboardingStore.getState().resetSelections();
  }
}
