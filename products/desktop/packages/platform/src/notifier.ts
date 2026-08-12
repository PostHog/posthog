export interface NotifyOptions {
  title: string;
  body: string;
  silent?: boolean;
  onClick?: () => void;
}

export interface INotifier {
  isSupported(): boolean;
  notify(options: NotifyOptions): void;
  setBadgeCount(count: number): void;
  requestAttention(): void;
}

export const NOTIFIER_SERVICE = Symbol.for("posthog.platform.notifier");
