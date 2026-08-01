import { CaretLeftIcon, StarIcon } from "@phosphor-icons/react";
import {
  Skeleton,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import { useChannelStarToggle } from "@posthog/ui/features/canvas/hooks/useChannelStars";
import {
  type Channel,
  useChannels,
} from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { PERSONAL_CHANNEL_NAME } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { showChannelList } from "@posthog/ui/features/canvas/stores/channelPaneStore";
import { track } from "@posthog/ui/shell/analytics";

// An overlay rather than a sibling: the back button fills the row, and nesting
// the star inside it would be a button within a button.
function RowStar({ channel }: { channel: Channel }) {
  const { isStarred, toggleStar } = useChannelStarToggle(channel);
  return (
    <button
      type="button"
      aria-label={isStarred ? "Unstar space" : "Star space"}
      onClick={() => {
        track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
          action_type: isStarred ? "unstar" : "star",
          surface: "sidebar",
          channel_id: channel.id,
        });
        toggleStar();
      }}
      // Parks in the row's reserved well: 8px padding + 6px gap = 14px from the
      // right edge.
      className="-translate-y-1/2 absolute top-1/2 right-[6px] flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-fill-hover hover:text-foreground"
    >
      <StarIcon size={14} weight={isStarred ? "fill" : "regular"} />
    </button>
  );
}

/**
 * The channel pane's header: the channel you're in, and the way back out of it.
 *
 * Clicking anywhere on the row slides the sidebar back to the channel list —
 * the list is where switching happens, so this row only has to be the door to
 * it. Leaving the channel scoped means the route (and the main pane) stay put.
 */
export function ChannelBackRow({ channelId }: { channelId: string }) {
  const spacesLayout = useChannelsLayout();
  const { channels, isLoading } = useChannels();
  const current = channels.find((c) => c.id === channelId);
  const showStar = current != null && current.name !== PERSONAL_CHANNEL_NAME;

  return (
    <div className="relative mx-2 mt-1">
      <Tooltip>
        <TooltipTrigger
          render={
            <button
              type="button"
              aria-label="Back to spaces"
              onClick={() => {
                track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
                  action_type: "browse_channels",
                  surface: "sidebar",
                  channel_id: channelId,
                });
                showChannelList();
              }}
              // Fixed height with an unconditional star well: sized off its
              // contents, a starrable channel ran 4px taller than #me and
              // everything below shifted on switch. No border — it's a row in
              // the sidebar like the ones under it, not a control sitting on
              // top.
              className="flex h-8 w-full items-center gap-1.5 rounded-md px-2 text-left transition-colors hover:bg-fill-hover"
            >
              <CaretLeftIcon
                size={12}
                className="shrink-0 text-muted-foreground"
                weight="bold"
              />
              <span className="flex w-4 shrink-0 items-center justify-center">
                {channelGlyph(current?.name, {
                  size: 14,
                  space: spacesLayout,
                  className: "text-muted-foreground",
                })}
              </span>
              <span className="min-w-0 flex-1 truncate font-semibold text-[13px] text-foreground">
                {current ? (
                  current.name
                ) : isLoading ? (
                  // A placeholder word here would read as a real channel named
                  // "channel"; a skeleton says "still loading" honestly.
                  <Skeleton className="h-3.5 w-24" />
                ) : (
                  "Unavailable"
                )}
              </span>
              <span aria-hidden className="size-6 shrink-0" />
            </button>
          }
        />
        <TooltipContent side="bottom">Back to spaces</TooltipContent>
      </Tooltip>
      {/* #me can't be starred, so its well stays empty — a greyed-out star read
          as a control you were being denied. The well itself is unconditional
          (see the button's reserved span), which is what keeps the row the same
          height on every space. */}
      {showStar && current && <RowStar channel={current} />}
    </div>
  );
}
