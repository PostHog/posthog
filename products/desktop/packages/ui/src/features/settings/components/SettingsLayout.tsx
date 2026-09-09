import { AnnouncementBanner } from "@posthog/ui/features/announcements/AnnouncementBanner";
import { ConnectivityBanner } from "@posthog/ui/features/connectivity/ConnectivityBanner";
import { SettingsPanel } from "@posthog/ui/features/settings/components/SettingsPanel";
import type { SettingsCategory } from "@posthog/ui/features/settings/types";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";

export function SettingsLayout({
  category,
  children,
}: {
  category: SettingsCategory;
  children?: ReactNode;
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
        <SettingsPanel activeCategory={category}>{children}</SettingsPanel>
      </div>
    </div>,
    container,
  );
}
