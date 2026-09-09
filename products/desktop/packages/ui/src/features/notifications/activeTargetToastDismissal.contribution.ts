import type { Contribution } from "@posthog/di/contribution";
import { toast } from "@posthog/ui/primitives/toast";
import { inject, injectable } from "inversify";
import { subscribeToRouterResolved } from "../../router/navigationBridge";
import { ACTIVE_VIEW_PROVIDER, type IActiveView } from "./identifiers";
import { targetKey } from "./routeNotification";

/**
 * Dismisses a target's toast once the user opens that target. A permission
 * toast is emitted while the user looks elsewhere, so opening the task from the
 * sidebar leaves the toast on screen — where it sits over the task's own
 * approval buttons and blocks them. Toasts carry the target key as their id
 * (see NotificationBus.showToast), so dismissing by that key clears the right
 * one. Started once at boot.
 */
@injectable()
export class ActiveTargetToastDismissal implements Contribution {
  constructor(
    @inject(ACTIVE_VIEW_PROVIDER)
    private readonly view: IActiveView,
  ) {}

  start(): void {
    subscribeToRouterResolved(() => this.dismissActiveTargetToast());
  }

  private dismissActiveTargetToast(): void {
    const target = this.view.getActiveTarget();
    if (!target) return;
    toast.dismiss(targetKey(target));
  }
}
