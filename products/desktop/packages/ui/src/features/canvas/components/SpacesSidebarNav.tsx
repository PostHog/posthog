import {
  HouseIcon,
  ListChecksIcon,
  PlusIcon,
  TrayIcon,
} from "@phosphor-icons/react";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { AllSpacesSection } from "@posthog/ui/features/canvas/components/AllSpacesSection";
import { ChannelNav } from "@posthog/ui/features/canvas/components/ChannelNav";
import { SpaceSection } from "@posthog/ui/features/canvas/components/SpaceSection";
import { useStarredChannelSlots } from "@posthog/ui/features/canvas/hooks/useStarredChannelSlots";
import { useInboxAllReports } from "@posthog/ui/features/inbox/hooks/useInboxAllReports";
import { SidebarItem } from "@posthog/ui/features/sidebar/components/SidebarItem";
import { CountBadge } from "@posthog/ui/primitives/CountBadge";
import {
  navigateToCode,
  navigateToInbox,
} from "@posthog/ui/router/navigationBridge";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { useRouterState } from "@tanstack/react-router";

/**
 * The static spaces nav: the shell keeps ChannelNav (the highlighted icon row).
 * Below it, Home / Tasks / Inbox as full-width items, then every starred space
 * with its tasks expanded inline, and the All spaces section.
 */
export function SpacesSidebarNav() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const isHome =
    pathname === "/code" || pathname === "/code/" || pathname === "/";
  const isTasks = pathname.startsWith("/code/tasks");
  const isInbox =
    pathname.startsWith("/code/inbox") || pathname.startsWith("/inbox");

  const { slots: pinnedSpaces } = useStarredChannelSlots();
  const { counts } = useInboxAllReports({
    ignoreFilters: true,
    refetchIntervalMs: 60_000,
  });

  return (
    <>
      {/* Icon row (kept as-is from the previous layout) */}
      <ChannelNav />

      {/* Home / Tasks / Inbox */}
      <div className="flex flex-col gap-px px-2">
        <SidebarItem
          depth={0}
          icon={<HouseIcon size={16} />}
          label="Home"
          isActive={isHome}
          onClick={() => navigateToCode()}
        />
        <SidebarItem
          depth={0}
          icon={<ListChecksIcon size={16} />}
          label="Tasks"
          isActive={isTasks}
          onClick={() => navigateToCode()}
        />
        <div className="group/inbox">
          <SidebarItem
            depth={0}
            icon={<TrayIcon size={16} />}
            label="Inbox"
            isActive={isInbox}
            badge={<CountBadge count={counts.pulls} />}
            endContent={
              <span className="flex items-center gap-0.5">
                <button
                  type="button"
                  aria-label="New task"
                  className="flex h-5 w-5 items-center justify-center rounded text-gray-10 opacity-0 transition-opacity hover:bg-(--gray-4) focus:opacity-100 group-hover/inbox:opacity-100"
                  onClick={(e) => {
                    e.stopPropagation();
                    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
                      action_type: "file_task",
                      surface: "sidebar",
                    });
                    openTaskInput();
                  }}
                >
                  <PlusIcon size={12} />
                </button>
              </span>
            }
            onClick={() => navigateToInbox()}
          />
        </div>
      </div>

      {/* Pinned (starred) spaces */}
      <div className="flex flex-col gap-px px-2">
        {pinnedSpaces.map((space) => (
          <SpaceSection key={space.id} channel={space} />
        ))}
      </div>

      {/* All spaces in the project */}
      <AllSpacesSection />
    </>
  );
}
