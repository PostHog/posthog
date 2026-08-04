import { CaretRightIcon, PlusIcon, StarIcon } from "@phosphor-icons/react";
import { Button, cn } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { CreateChannelModal } from "@posthog/ui/features/canvas/components/CreateChannelModal";
import {
  useChannelStarMutations,
  useChannelStars,
} from "@posthog/ui/features/canvas/hooks/useChannelStars";
import {
  type Channel,
  useChannels,
} from "@posthog/ui/features/canvas/hooks/useChannels";
import { PERSONAL_CHANNEL_NAME } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { useSpacesSidebarStore } from "@posthog/ui/features/canvas/stores/spacesSidebarStore";
import { SidebarItem } from "@posthog/ui/features/sidebar/components/SidebarItem";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useMemo, useState } from "react";

/**
 * The project's space directory, docked at the bottom of the sidebar. The
 * header is shaped exactly like a pinned space row (same caret, same inset) and
 * folding it open grows the section upward to a capped height, then the list
 * scrolls. Clicking a row opens the space; the hover star is what pins it into
 * the sidebar above — pinned rows wear their star filled so the directory
 * shows what's already up there. The personal space isn't listed: it can't be
 * pinned or shared, and it's always first in the pinned list anyway.
 */
export function AllSpacesSection() {
  const open = useSpacesSidebarStore((s) => s.openAddSpace);
  const toggle = useSpacesSidebarStore((s) => s.toggleAddSpace);
  const [createOpen, setCreateOpen] = useState(false);

  const { channels } = useChannels();
  const { starredRefToShortcutId } = useChannelStars();
  const { star, unstar } = useChannelStarMutations();
  const setCurrentChannel = useCurrentChannelStore((s) => s.setCurrentChannel);
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  const spaces = useMemo(
    () =>
      channels
        .filter((c) => c.name !== PERSONAL_CHANNEL_NAME)
        .sort((a, b) => a.name.localeCompare(b.name)),
    [channels],
  );

  const openSpace = (channel: Channel) => {
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "nav_click",
      surface: "sidebar",
      channel_id: channel.id,
    });
    setCurrentChannel(channel.id);
    void navigate({
      to: "/website/$channelId",
      params: { channelId: channel.id },
    });
  };

  const togglePin = (channel: Channel) => {
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
    <div className="shrink-0 border-border border-t">
      <div className="flex flex-col gap-px px-2 pt-1 pb-2">
        {/* Same shape as a pinned space row, so the carets line up. */}
        <Button
          variant="default"
          left
          aria-expanded={open}
          onClick={toggle}
          className="w-full gap-1.5 text-left"
        >
          <CaretRightIcon
            size={12}
            className={cn(
              "shrink-0 text-muted-foreground transition-transform",
              open && "rotate-90",
            )}
          />
          <span className="min-w-0 flex-1 truncate font-medium text-[13px] text-muted-foreground group-hover/button:text-foreground">
            All spaces
          </span>
        </Button>

        {open && (
          <>
            <div className="flex max-h-64 flex-col gap-px overflow-y-auto">
              {spaces.map((channel) => {
                const shortcutId = starredRefToShortcutId.get(channel.path);
                const base = `/website/${channel.id}`;
                const isActive =
                  pathname === base || pathname.startsWith(`${base}/`);
                return (
                  // Overlay, not endContent: the row is a button already, and
                  // a star nested inside it would be a button within a button.
                  <div key={channel.id} className="group/space relative">
                    <SidebarItem
                      depth={1}
                      label={channel.name}
                      isActive={isActive}
                      onClick={() => openSpace(channel)}
                      // Dragging a directory row up into the pinned area pins
                      // it — same result as the star, one gesture instead.
                      draggable
                      onDragStart={(e) => {
                        e.dataTransfer.setData("text/x-space-id", channel.id);
                        e.dataTransfer.effectAllowed = "copy";
                      }}
                      // Star well, so the name truncates clear of the star.
                      endContent={
                        <span aria-hidden className="size-5 shrink-0" />
                      }
                    />
                    <Button
                      variant="default"
                      size="icon-sm"
                      aria-label={shortcutId ? "Unpin space" : "Pin space"}
                      onClick={() => togglePin(channel)}
                      className={cn(
                        "-translate-y-1/2 absolute top-1/2 right-[2px] text-muted-foreground transition-opacity",
                        shortcutId
                          ? "opacity-100"
                          : "opacity-0 focus-visible:opacity-100 group-hover/space:opacity-100",
                      )}
                    >
                      <StarIcon
                        size={13}
                        weight={shortcutId ? "fill" : "regular"}
                      />
                    </Button>
                  </div>
                );
              })}
            </div>
            {/* Below the scroll region so it's reachable without scrolling
                the whole directory. */}
            <SidebarItem
              depth={1}
              icon={<PlusIcon size={14} className="text-muted-foreground" />}
              label={<span className="text-muted-foreground">New space</span>}
              onClick={() => setCreateOpen(true)}
            />
            <CreateChannelModal
              open={createOpen}
              onOpenChange={setCreateOpen}
            />
          </>
        )}
      </div>
    </div>
  );
}
