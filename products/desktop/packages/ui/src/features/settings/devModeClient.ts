/**
 * Host-provided client for the developer mode flag that backs the dev
 * toolbar. Hosts that ship a dev toolbar (Electron) bind this in their
 * renderer container; hosts without one leave it unbound and the settings
 * row is hidden.
 */
export interface DevModeClient {
  getDevMode(): boolean;
  setDevMode(enabled: boolean): Promise<void>;
  /** Returns an unsubscribe function. */
  onDevModeChanged(listener: (devMode: boolean) => void): () => void;
}

export const DEV_MODE_CLIENT = Symbol.for("posthog.ui.DevModeClient");
