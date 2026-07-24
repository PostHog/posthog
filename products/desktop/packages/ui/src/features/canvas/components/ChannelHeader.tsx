import { HashIcon } from "@phosphor-icons/react";
import { Button, cn } from "@posthog/quill";
import { ChannelTabs } from "@posthog/ui/features/canvas/components/ChannelTabs";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useMarkChannelSeen } from "@posthog/ui/features/canvas/hooks/useMarkChannelSeen";
import { Text } from "@radix-ui/themes";
import { useNavigate, useRouterState } from "@tanstack/react-router";

// The shared channel header: a clickable "# channel" that doubles as the Home
// item — it routes to the channel home (`/website/$channelId`, like the sidebar
// channel row) and highlights `bg-fill-selected` while you're there, the same
// pathname-driven active state the rest of the channel tab strip uses. Followed
// by that strip (Artifacts / Recents / CONTEXT.md), rendered into the
// header bar by every channel view so the tabs stay in view.
export function ChannelHeader({ channelId }: { channelId: string }) {
  const navigate = useNavigate();
  const { channels } = useChannels();
  const channelName = channels.find((c) => c.id === channelId)?.name;
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const isHome = pathname === `/website/${channelId}`;
  // Every channel surface renders this header, so it is where "the viewer is
  // in this channel" is known — and therefore where the channel is marked read.
  useMarkChannelSeen(channelName);

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
        <HashIcon size={20} className="shrink-0 text-muted-foreground/80" />
        <Text className="min-w-0 truncate font-medium" title={channelName}>
          {channelName ?? "Channel"}
        </Text>
      </Button>
      <ChannelTabs channelId={channelId} />
    </div>
  );
}
