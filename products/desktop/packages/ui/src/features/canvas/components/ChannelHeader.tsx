import { Button, cn } from "@posthog/quill";
import { ChannelTabs } from "@posthog/ui/features/canvas/components/ChannelTabs";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useMarkChannelSeen } from "@posthog/ui/features/canvas/hooks/useMarkChannelSeen";
import { Text } from "@radix-ui/themes";
import { useNavigate, useRouterState } from "@tanstack/react-router";

// The shared channel header. The new layout drops the section tab strip — the
// channel sidebar carries those entries — while flag off keeps it. Starring
// lives on the sidebar back row and the channel list, not here.
export function ChannelHeader({ channelId }: { channelId: string }) {
  const navigate = useNavigate();
  const channelsLayout = useChannelsLayout();
  const { channels } = useChannels();
  const channelName = channels.find((c) => c.id === channelId)?.name;
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const isHome = pathname === `/website/${channelId}`;
  // Every channel surface renders this header, so mark the channel read here.
  useMarkChannelSeen(channelId);

  return (
    <div className="flex min-w-0 items-center gap-2">
      <Button
        type="button"
        data-selected={isHome || undefined}
        onClick={() =>
          void navigate({ to: "/website/$channelId", params: { channelId } })
        }
        size="sm"
        className={cn("min-w-0", isHome ? "bg-fill-selected" : "")}
      >
        {channelGlyph(channelName, {
          size: 20,
          space: channelsLayout,
          className: "shrink-0 text-muted-foreground/80",
        })}
        <Text className="min-w-0 truncate font-medium" title={channelName}>
          {channelName ?? (channelsLayout ? "Space" : "Channel")}
        </Text>
      </Button>
      {!channelsLayout && <ChannelTabs channelId={channelId} />}
    </div>
  );
}
