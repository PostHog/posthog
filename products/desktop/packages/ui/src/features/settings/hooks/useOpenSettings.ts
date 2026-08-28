import { useSettingsPageStore } from "@posthog/ui/features/settings/stores/settingsPageStore";
import type { SettingsCategory } from "@posthog/ui/features/settings/types";
import * as nav from "@posthog/ui/router/navigationBridge";
import { useRouterState } from "@tanstack/react-router";
import { useCallback } from "react";

interface SettingsContext {
  repoPath?: string;
}

/**
 * Open the settings page. Optionally pin context (e.g. repoPath for the
 * worktrees page) or fire a one-shot initial action (e.g. "create-new" to
 * open the create-environment form on entry). The store holds these; the
 * URL holds the category.
 */
export function openSettings(
  category: SettingsCategory = "general",
  contextOrAction?: SettingsContext | string,
): void {
  prepareSettingsPage(contextOrAction);
  // A caller already inside settings is switching category, so replace rather
  // than stack: one closeSettings() back-step must exit to the app instead of
  // walking back through the categories visited.
  nav.navigateToSettings(category, { replace: nav.isOnSettingsRoute() });
}

/**
 * Reset/pin the settings page store without navigating — for `<Link>` CTAs
 * that own the navigation themselves (the render={<Link …/>} convention) but
 * must not carry stale context or a one-shot action into the page.
 */
export function prepareSettingsPage(
  contextOrAction?: SettingsContext | string,
): void {
  const store = useSettingsPageStore.getState();
  if (typeof contextOrAction === "string") {
    store.setContext({});
    store.setInitialAction(contextOrAction);
  } else {
    store.setContext(contextOrAction ?? {});
    store.setInitialAction(null);
  }
  store.setFormMode(false);
}

/**
 * Leave the settings page for a route the caller navigates to itself. Resets
 * the store without the history pop `closeSettings` does, which would land the
 * user back on the prior route after their own navigation.
 */
export function leaveSettings(): void {
  useSettingsPageStore.getState().reset();
}

/**
 * Close the settings page — returns the user to their prior route via
 * router history. If they came in via a deep link, falls back to /code.
 */
export function closeSettings(): void {
  useSettingsPageStore.getState().reset();
  if (!nav.isOnSettingsRoute()) return;
  if (nav.canGoBackInHistory()) {
    nav.goBackInHistory();
  } else {
    nav.navigateToNewTask();
  }
}

export function useCloseSettings(): typeof closeSettings {
  return useCallback(closeSettings, []);
}

/**
 * True when the current route is anywhere under `/settings/*`.
 */
export function useIsSettingsOpen(): boolean {
  return useRouterState({
    select: (s) => s.matches.some((m) => m.routeId.startsWith("/settings")),
  });
}
