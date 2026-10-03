import { ArrowUUpLeftIcon, GearIcon, StarIcon } from "@phosphor-icons/react";
import {
  Button,
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
import { useNavigate } from "@tanstack/react-router";

function RowStar({ channel }: { channel: Channel }) {
  const { isStarred, toggleStar } = useChannelStarToggle(channel);
  const label = isStarred ? "Unstar space" : "Star space";
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="default"
            size="icon-sm"
            aria-label={label}
            onClick={() => {
              track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
                action_type: isStarred ? "unstar" : "star",
                surface: "sidebar",
                channel_id: channel.id,
              });
              toggleStar();
            }}
            className="text-muted-foreground"
          >
            <StarIcon size={14} weight={isStarred ? "fill" : "regular"} />
          </Button>
        }
      />
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

export function ChannelBackRow({ channelId }: { channelId: string }) {
  const navigate = useNavigate();
  const spacesLayout = useChannelsLayout();
  const { channels, isLoading } = useChannels();
  const current = channels.find((c) => c.id === channelId);
  const showStar = current != null && current.channelType !== "personal";
  const glyph = channelGlyph(current?.name, {
    personal: current?.channelType === "personal",
    private: current?.channelType === "private",
    size: 14,
    space: spacesLayout,
    className: "text-muted-foreground",
  });

  return (
    <div className="group/back flex h-10 items-center gap-0.5 border-border border-b px-1.5 pt-1.5 pb-2">
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
              className="min-w-0 flex-1 gap-1.5 text-left"
            >
              <ArrowUUpLeftIcon
                size={12}
                weight="bold"
                className="shrink-0 text-primary"
              />
              {glyph && (
                <span className="flex w-4 shrink-0 items-center justify-center">
                  {glyph}
                </span>
              )}
              <span className="min-w-0 flex-1 truncate font-semibold text-[13px] text-foreground">
                {current ? (
                  current.name
                ) : isLoading ? (
                  <Skeleton className="h-3.5 w-24" />
                ) : (
                  "Unavailable"
                )}
              </span>
              <Kbd className="mr-0! shrink-0 opacity-0 transition-opacity group-focus-within/back:opacity-60 group-hover/back:opacity-60">
                {formatHotkey(SHORTCUTS.FOCUS_SIDEBAR_SEARCH)}
              </Kbd>
            </Button>
          }
        />
        <TooltipContent side="bottom">Back to spaces</TooltipContent>
      </Tooltip>
      {showStar && current && <RowStar channel={current} />}
      {current && (
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                variant="default"
                size="icon-sm"
                aria-label="Space settings"
                className="text-muted-foreground"
                onClick={() =>
                  void navigate({
                    to: "/spaces/$channelId/settings",
                    params: { channelId },
                  })
                }
              >
                <GearIcon size={14} />
              </Button>
            }
          />
          <TooltipContent>Space settings</TooltipContent>
        </Tooltip>
      )}
    </div>
  );
}
