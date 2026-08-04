import {
  CaretRightIcon,
  CheckIcon,
  CubeIcon,
  StarIcon,
} from "@phosphor-icons/react";
import { cn } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import {
  useChannelStarMutations,
  useChannelStars,
} from "@posthog/ui/features/canvas/hooks/useChannelStars";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { PERSONAL_CHANNEL_NAME } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useSpacesSidebarStore } from "@posthog/ui/features/canvas/stores/spacesSidebarStore";
import { SidebarItem } from "@posthog/ui/features/sidebar/components/SidebarItem";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useMemo } from "react";

/**
 * The "All spaces" toggle: every space in the project as a row with a hover
 * pin/star. Under the new sidebar the starred spaces are the pinned ones, so
 * this list is the project's directory — clicking a row pins it (stars), and
 * the row carries the star back out again. Personal channel is listed by
 * name only (it can't be pinned).
 */
export function AllSpacesSection() {
  const open = useSpacesSidebarStore((s) => s.openAddSpace);
  const toggle = useSpacesSidebarStore((s) => s.toggleAddSpace);

  const { channels } = useChannels();
  const { starredRefToShortcutId } = useChannelStars();
  const { star, unstar } = useChannelStarMutations();

  const allSpaces = useMemo(() => channels, [channels]);

  const togglePin = (channelId: string) => {
    const channel = channels.find((c) => c.id === channelId);
    if (!channel || channel.name === PERSONAL_CHANNEL_NAME) return;
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
    <div className="flex flex-col gap-px">
      <div className="group/allspaces">
        <SidebarItem
          depth={0}
          icon={<CubeIcon size={16} />}
          label="All spaces"
          badge={
            <CaretRightIcon
              size={12}
              className={cn(
                "text-muted-foreground transition-transform",
                open && "rotate-90",
              )}
            />
          }
          onClick={toggle}
          aria-expanded={open}
        />
      </div>
      {open &&
        allSpaces.map((channel) => {
          const shortcutId = starredRefToShortcutId.get(channel.path);
          const isPersonal = channel.name === PERSONAL_CHANNEL_NAME;
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
                  isPersonal ? undefined : (
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
                  )
                }
              />
            </div>
          );
        })}
    </div>
  );
}
