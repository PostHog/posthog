import type {
  ExternalAppsFocusCoordinator,
  ExternalAppsFocusParams,
  ExternalAppsFocusSession,
} from "@posthog/core/external-apps/identifiers";
import type { FocusSagaResult } from "@posthog/core/focus/service";
import { injectable } from "inversify";
import { useFocusStore } from "../focus/focusStore";

@injectable()
export class FocusStoreCoordinator implements ExternalAppsFocusCoordinator {
  getSession(): ExternalAppsFocusSession | null {
    const session = useFocusStore.getState().session;
    return session ? { worktreePath: session.worktreePath } : null;
  }

  enableFocus(params: ExternalAppsFocusParams): Promise<FocusSagaResult> {
    return useFocusStore.getState().enableFocus(params);
  }
}
