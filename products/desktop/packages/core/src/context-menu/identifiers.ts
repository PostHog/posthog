export interface ContextMenuExternalApp {
  id: string;
  name: string;
  icon?: string;
}

export interface IContextMenuExternalApps {
  getDetectedApps(): Promise<ContextMenuExternalApp[]>;
  getLastUsed(): Promise<{ lastUsedApp?: string }>;
}

export const CONTEXT_MENU_EXTERNAL_APPS_SERVICE = Symbol.for(
  "posthog.core.contextMenuExternalAppsService",
);

export const CONTEXT_MENU_CONTROLLER = Symbol.for(
  "posthog.core.contextMenuController",
);
