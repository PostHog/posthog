export interface IAppLifecycle {
  whenReady(): Promise<void>;
  quit(): void;
  exit(code?: number): void;
  onQuit(handler: () => void | Promise<void>): () => void;
  registerDeepLinkScheme(scheme: string): void;
}

export const APP_LIFECYCLE_SERVICE = Symbol.for(
  "posthog.platform.appLifecycle",
);
