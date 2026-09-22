/**
 * UI-side port for the quick-ask panel's settings. The global shortcut is
 * registered by the host (`apps/code` main process); this is the thin,
 * host-neutral surface the settings UI talks to. The desktop host binds a
 * tRPC-backed adapter; hosts without a quick-ask panel leave it unbound and
 * the settings card hides itself.
 */

export interface QuickAskState {
  /** Whether the quick-ask panel is available in this build. */
  enabled: boolean;
  /** The user toggle; off unregisters the shortcut and drops the panel. */
  active: boolean;
  /** The configured Electron accelerator. */
  shortcut: string;
  /** False when another app owns the accelerator. */
  registered: boolean;
  /** Space new threads file into; empty means the personal space. */
  defaultChannelId: string;
  /** Repos the sandbox clones; empty defers to the space's repositories. */
  defaultRepositories: string[];
  defaultGithubIntegrationId: number;
  /** Empty strings follow the adapter/model defaults. */
  defaultAdapter: string;
  defaultModel: string;
  defaultEffort: string;
}

export interface QuickAskSettingsPatch {
  active?: boolean;
  defaultChannelId?: string;
  defaultRepositories?: string[];
  defaultGithubIntegrationId?: number;
  defaultAdapter?: string;
  defaultModel?: string;
  defaultEffort?: string;
}

export interface QuickAskSettingsClient {
  getState(): Promise<QuickAskState>;
  setShortcut(accelerator: string): Promise<QuickAskState>;
  setSettings(patch: QuickAskSettingsPatch): Promise<QuickAskState>;
}

export const QUICK_ASK_SETTINGS_CLIENT = Symbol.for(
  "posthog.ui.quickAsk.settingsClient",
);
