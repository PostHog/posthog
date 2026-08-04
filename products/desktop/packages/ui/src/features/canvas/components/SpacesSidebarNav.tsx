import {
  CaretRightIcon,
  CheckIcon,
  HouseIcon,
  ListChecksIcon,
  PlusIcon,
  StarIcon,
  TrayIcon,
} from "@phosphor-icons/react";
import { cn } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { ChannelNav } from "@posthog/ui/features/canvas/components/ChannelNav";
import { SpaceSection } from "@posthog/ui/features/canvas/components/SpaceSection";
import {
  useChannelStarMutations,
  useChannelStars,
} from "@posthog/ui/features/canvas/hooks/useChannelStars";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useStarredChannelSlots } from "@posthog/ui/features/canvas/hooks/useStarredChannelSlots";
import { PERSONAL_CHANNEL_NAME } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useSpacesSidebarSelectionStore } from "@posthog/ui/features/canvas/stores/spacesSidebarSelectionStore";
import { useSpacesSidebarStore } from "@posthog/ui/features/canvas/stores/spacesSidebarStore";
import { useInboxAllReports } from "@posthog/ui/features/inbox/hooks/useInboxAllReports";
import { SidebarItem } from "@posthog/ui/features/sidebar/components/SidebarItem";
import { CountBadge } from "@posthog/ui/primitives/CountBadge";
import { toast } from "@posthog/ui/primitives/toast";
import {
  navigateToCode,
  navigateToInbox,
} from "@posthog/ui/router/navigationBridge";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { useRouterState } from "@tanstack/react-router";
import { useMemo } from "react";

/**
 * The static spaces nav: the shell keeps ChannelNav (the highlighted icon row).
 * Below it, Home / Tasks / Inbox as full-width items, then every starred space
 * with its tasks expanded inline, then an "Add space" toggle that renders all
 * project spaces as plain rows with a hover pin/star action, and Preview.
 */
export function SpacesSidebarNav() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const isHome =
    pathname === "/code" || pathname === "/code/" || pathname === "/";
  const isTasks = pathname.startsWith("/code/tasks");
  const isInbox =
    pathname.startsWith("/code/inbox") || pathname.startsWith("/inbox");

  const { slots: pinnedSpaces } = useStarredChannelSlots();
  const { star, unstar } = useChannelStarMutations();
  const { starredRefToShortcutId } = useChannelStars();
  const { channels } = useChannels();
  const { counts } = useInboxAllReports({
    ignoreFilters: true,
    refetchIntervalMs: 60_000,
  });

  const openAddSpace = useSpacesSidebarStore((s) => s.openAddSpace);
  const toggleAddSpace = useSpacesSidebarStore((s) => s.toggleAddSpace);
  const showPreview = useSpacesSidebarSelectionStore((s) => s.showPreview);
  const togglePreview = useSpacesSidebarSelectionStore((s) => s.togglePreview);

  const allSpaces = useMemo(
    () => channels.filter((c) => c.name !== PERSONAL_CHANNEL_NAME),
    [channels],
  );

  const togglePin = (channelId: string) => {
    const channel = channels.find((c) => c.id === channelId);
    if (!channel) return;
    const shortcutId = starredRefToShortcutId.get(channel.path);
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: shortcutId ? "unstar" : "star",
      surface: "sidebar",
      channel_id: channel.id,
    });
    const run = shortcutId ? unstar(shortcutId) : star(channel);
    run.catch((error: unknown) =>
      toast.error(shortcutId ? "Couldn't unpin space" : "Couldn't pin space", {
        description: error instanceof Error ? error.message : String(error),
      }),
    );
  };

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
                <button
                  type="button"
                  aria-label="Inbox menu"
                  className="flex h-5 w-5 items-center justify-center rounded text-gray-10 opacity-0 transition-opacity hover:bg-(--gray-4) focus:opacity-100 group-hover/inbox:opacity-100"
                  onClick={(e) => {
                    e.stopPropagation();
                    navigateToInbox();
                  }}
                >
                  <CaretRightIcon size={12} />
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

      {/* Add space: a full toggle like the others, rendering every space in the
          project so it can be pinned/unpinned; clicking a row pins it. */}
      <div className="flex flex-col gap-px px-2">
        <div className="group/addspace">
          <SidebarItem
            depth={0}
            label={
              <>
                <CaretRightIcon
                  size={12}
                  className={cn(
                    "mr-1 inline-block text-muted-foreground transition-transform",
                    openAddSpace && "rotate-90",
                  )}
                />
                Add space
              </>
            }
            endContent={
              <button
                type="button"
                aria-label="New space"
                className="flex h-5 w-5 items-center justify-center rounded text-gray-10 opacity-0 transition-opacity hover:bg-(--gray-4) focus:opacity-100 group-hover/addspace:opacity-100"
                onClick={(e) => {
                  e.stopPropagation();
                  track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
                    action_type: "create",
                    surface: "sidebar",
                  });
                  toggleAddSpace();
                }}
              >
                <PlusIcon size={12} />
              </button>
            }
            onClick={toggleAddSpace}
            aria-expanded={openAddSpace}
          />
        </div>
        {openAddSpace &&
          allSpaces.map((channel) => {
            const shortcutId = starredRefToShortcutId.get(channel.path);
            return (
              <div key={channel.id} className="group/space">
                <SidebarItem
                  depth={1}
                  label={
                    <>
                      {shortcutId ? (
                        <CheckIcon
                          size={12}
                          className="mr-1 inline-block text-yellow-9"
                        />
                      ) : null}
                      {channel.name}
                    </>
                  }
                  onClick={() => togglePin(channel.id)}
                  endContent={
                    <button
                      type="button"
                      aria-label={shortcutId ? "Unpin space" : "Pin space"}
                      className={cn(
                        "flex h-5 w-5 items-center justify-center rounded text-gray-10 transition-opacity hover:bg-(--gray-4) focus:opacity-100",
                        shortcutId
                          ? "text-yellow-9 opacity-100"
                          : "opacity-0 group-hover/space:opacity-100",
                      )}
                      onClick={(e) => {
                        e.stopPropagation();
                        togglePin(channel.id);
                      }}
                    >
                      <StarIcon
                        size={13}
                        weight={shortcutId ? "fill" : "regular"}
                      />
                    </button>
                  }
                />
              </div>
            );
          })}

        {/* Preview toggle */}
        <div className="group/preview">
          <SidebarItem
            depth={0}
            label={
              <>
                <CaretRightIcon
                  size={12}
                  className={cn(
                    "mr-1 inline-block text-muted-foreground transition-transform",
                    showPreview && "rotate-90",
                  )}
                />
                Preview
              </>
            }
            endContent={
              <button
                type="button"
                aria-label="Preview options"
                className="flex h-5 w-5 items-center justify-center rounded text-gray-10 opacity-0 transition-opacity hover:bg-(--gray-4) focus:opacity-100 group-hover/preview:opacity-100"
                onClick={(e) => e.stopPropagation()}
              >
                <PlusIcon size={12} />
              </button>
            }
            onClick={togglePreview}
            aria-expanded={showPreview}
          />
        </div>
      </div>
    </>
  );
}
