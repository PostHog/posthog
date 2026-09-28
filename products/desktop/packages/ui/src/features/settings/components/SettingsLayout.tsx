import { AnnouncementBanner } from "@posthog/ui/features/announcements/AnnouncementBanner";
import { ConnectivityBanner } from "@posthog/ui/features/connectivity/ConnectivityBanner";
import { SettingsDialogFrame } from "@posthog/ui/features/settings/components/SettingsDialogFrame";
import { SettingsPanel } from "@posthog/ui/features/settings/components/SettingsPanel";
import { closeSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import {
  type SettingsCategory,
  settingsPageRevealsApp,
} from "@posthog/ui/features/settings/types";
import { navigateToSettings } from "@posthog/ui/router/navigationBridge";
import { getRouterOrNull } from "@posthog/ui/router/routerRef";
import type { ReactNode } from "react";

export function SettingsLayout({
  category,
  children,
  childBackHref,
}: {
  category: SettingsCategory;
  children?: ReactNode;
  /**
   * Where the panel's Back button goes when hosting child content. A child
   * page reached through this portal (a report opened from settings) knows its
   * own source; without this the Back handler rebuilds the target from the
   * category alone and drops the child's context (the open agent, its tab and
   * the nested source).
   */
  childBackHref?: string;
}) {
  const back = children
    ? childBackHref
      ? // Same shape as leaving settings for a recorded source: push the href
        // and keep this tab's tag, so the composer session keyed on it
        // survives.
        () => {
          const router = getRouterOrNull();
          router?.history.push(childBackHref, {
            tabId: router.history.location.state.tabId,
          });
        }
      : () => navigateToSettings(category)
    : undefined;

  // A report opened inside settings sits on its own route, where
  // `closeSettings` has no settings route to leave; step back out instead.
  const dismiss = back ?? closeSettings;

  return (
    <SettingsDialogFrame
      onDismiss={dismiss}
      onEscape={back}
      seeThrough={!children && settingsPageRevealsApp(category)}
    >
      <ConnectivityBanner />
      <AnnouncementBanner />
      <div className="flex min-h-0 flex-1">
        <SettingsPanel
          activeCategory={category}
          onClose={dismiss}
          onBack={back}
        >
          {children}
        </SettingsPanel>
      </div>
    </SettingsDialogFrame>
  );
}
