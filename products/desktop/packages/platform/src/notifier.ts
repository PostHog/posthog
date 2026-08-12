export interface NotifyOptions {
  title: string;
  body: string;
  silent?: boolean;
  onClick?: () => void;
}

export interface INotifier {
  isSupported(): boolean;
  notify(options: NotifyOptions): void;
  /**
   * How many items are waiting on the user, where 0 clears the indicator.
   * Called whenever the count changes rather than when an event fires, so the
   * badge still shows work that arrived while the app was focused.
   */
  setUnreadCount(count: number): void;
  /**
   * Stop a pending attention signal, such as a flashing taskbar frame, without
   * touching the unread count. Called when the window regains focus, because
   * being looked at answers "over here" but does not mean the work was handled.
   */
  clearAttention(): void;
  requestAttention(): void;
}

export const NOTIFIER_SERVICE = Symbol.for("posthog.platform.notifier");
