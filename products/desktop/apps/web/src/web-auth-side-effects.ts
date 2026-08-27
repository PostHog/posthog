import type { CloudRegion } from "@posthog/shared";
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
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { inject, injectable } from "inversify";

// Web counterpart of the desktop RendererAuthSideEffects. Identical store/query
// coordination, minus the desktop SessionService reset — web cloud sessions are
// owned by the core SessionService, not a renderer singleton.
@injectable()
export class WebAuthSideEffects implements IAuthSideEffects {
  constructor(
    @inject(BROWSER_TABS_CLIENT)
    private readonly browserTabsClient: BrowserTabsClient,
  ) {}

  onAuthSuccess(_region: CloudRegion, _projectId: number | null): void {
    void refreshAuthStateQuery();
    useAuthUiStateStore.getState().clearStaleRegion();
  }

  beforeProjectSwitch(): void {}

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
