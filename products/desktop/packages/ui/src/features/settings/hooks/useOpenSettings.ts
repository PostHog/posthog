import { useSettingsPageStore } from "@posthog/ui/features/settings/stores/settingsPageStore";
import type { SettingsCategory } from "@posthog/ui/features/settings/types";
import * as nav from "@posthog/ui/router/navigationBridge";
import { useReportSourceHref } from "@posthog/ui/router/reportNavigation";
import { useRouterState } from "@tanstack/react-router";

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
  // than stack: the categories visited are not steps to walk back through.
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

/** A deep link carries no `from`, so it falls back to /code. */
export function closeSettings(): void {
  useSettingsPageStore.getState().reset();
  if (!nav.isOnSettingsRoute()) return;
  nav.leaveSettingsRoute();
}

/**
 * True when settings covers the screen: a settings route, or a report opened
 * from one (it hosts the same portal).
 */
export function useIsSettingsOpen(): boolean {
  const route = useRouterState({
    select: (s) => s.matches.some((m) => nav.isSettingsRouteId(m.routeId)),
  });
  const reportFromSettings = useReportSourceHref()?.startsWith("/settings/");
  return route || reportFromSettings === true;
}
