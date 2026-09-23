import { AnnouncementBanner } from "@posthog/ui/features/announcements/AnnouncementBanner";
import { ConnectivityBanner } from "@posthog/ui/features/connectivity/ConnectivityBanner";
import { SettingsPanel } from "@posthog/ui/features/settings/components/SettingsPanel";
import type { SettingsCategory } from "@posthog/ui/features/settings/types";
import { navigateToSettings } from "@posthog/ui/router/navigationBridge";
import { getRouterOrNull } from "@posthog/ui/router/routerRef";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";

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
  const container =
    document.getElementById("portal-container") ?? document.body;
  return createPortal(
    <div
      className="absolute inset-0 z-[100] flex flex-col bg-(--color-background)"
      data-overlay="settings"
    >
      <ConnectivityBanner />
      <AnnouncementBanner />
      <div className="flex min-h-0 flex-1">
        <SettingsPanel
          activeCategory={category}
          onClose={
            children
              ? childBackHref
                ? // Same shape as leaving settings for a recorded source: push
                  // the href and keep this tab's tag, so the composer session
                  // keyed on it survives.
                  () => {
                    const router = getRouterOrNull();
                    router?.history.push(childBackHref, {
                      tabId: router.history.location.state.tabId,
                    });
                  }
                : () => navigateToSettings(category)
              : undefined
          }
        >
          {children}
        </SettingsPanel>
      </div>
    </div>,
    container,
  );
}
