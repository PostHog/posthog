import { ArrowUUpLeftIcon, StarIcon } from "@phosphor-icons/react";
import {
  Button,
  cn,
  Kbd,
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
import { showChannelList } from "@posthog/ui/features/canvas/stores/channelPaneStore";
import {
  formatHotkey,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";
import { track } from "@posthog/ui/shell/analytics";

// An overlay rather than a sibling: the back button fills the row, and nesting
// the star inside it would be a button within a button.
function RowStar({ channel }: { channel: Channel }) {
  const { isStarred, toggleStar } = useChannelStarToggle(channel);
  return (
    <Button
      variant="default"
      size="icon-sm"
      aria-label={isStarred ? "Unstar space" : "Star space"}
      onClick={() => {
        track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
          action_type: isStarred ? "unstar" : "star",
          surface: "sidebar",
          channel_id: channel.id,
        });
        toggleStar();
      }}
      // Parks in the row's reserved well: 8px padding + 3px gap = 11px from the
      // right edge.
      className="-translate-y-1/2 absolute top-1/2 right-2 text-muted-foreground"
    >
      <StarIcon size={14} weight={isStarred ? "fill" : "regular"} />
    </Button>
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
  const showStar = current != null && current.channelType !== "personal";
  const glyph = channelGlyph(current?.name, {
    personal: current?.channelType === "personal",
    size: 14,
    space: spacesLayout,
    className: "text-muted-foreground",
  });

  return (
    <div className="relative h-10 border-border border-b px-1.5 pt-1.5 pb-2">
      <Tooltip>
        <TooltipTrigger
          render={
            <Button
              variant="default"
              left
              aria-label="Back to spaces"
              onClick={() => {
                track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
                  action_type: "browse_channels",
                  surface: "sidebar",
                  channel_id: channelId,
                });
                showChannelList({ animate: true });
              }}
              // Quill's own height and radius, so this reads as one of the rows
              // under it rather than a control sitting on top. The right padding
              // is the star's well — the star is an overlay, because a button
              // can't nest one, so without it the row's own content runs under
              // the star. Padding rather than a spacer element: quill hides an
              // empty one (`empty:hidden`), which is how the shortcut hint ended
              // up sitting beneath the star.
              className={cn(
                "w-full gap-1.5 pr-1 text-left",
                showStar && "pr-8",
              )}
            >
              {/* The way out of a space, in the brand's own colour: a muted
                  caret read as decoration on a header rather than the control
                  it is, and people could not find their way back to the list. */}
              <ArrowUUpLeftIcon
                size={12}
                weight="bold"
                className="shrink-0 text-primary"
              />
              {/* Only #me still has a glyph under the layout, and its well is
                  drawn only when there's something in it — an empty 16px column
                  in front of every other space's name is worse than the name
                  starting where the caret leaves off. */}
              {glyph && (
                <span className="flex w-4 shrink-0 items-center justify-center text-foreground">
                  {glyph}
                </span>
              )}
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
              {/* Same key as the search box's hint: from inside a space it is
                  the way back to the list, which is what this row does. */}
              <Kbd className="mr-0! shrink-0 opacity-50">
                {formatHotkey(SHORTCUTS.FOCUS_SIDEBAR_SEARCH)}
              </Kbd>
              {/* The star's well. Its height is unconditional — it is what
                  sets the row's height, and a row that changed height between a
                  starrable space and #me made everything below it jump on
                  switch. Its width is not: with no star to hold, an empty
                  column just pushes the shortcut hint off the edge. */}
              <span
                aria-hidden
                className={cn(
                  "h-6 shrink-0 empty:hidden",
                  showStar ? "w-6" : "w-0",
                )}
              />
            </Button>
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
