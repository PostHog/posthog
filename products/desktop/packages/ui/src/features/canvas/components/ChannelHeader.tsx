import { Button, cn } from "@posthog/quill";
import { ChannelBreadcrumb } from "@posthog/ui/features/canvas/components/ChannelBreadcrumb";
import { ChannelTabs } from "@posthog/ui/features/canvas/components/ChannelTabs";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import {
  type ChannelPageKey,
  channelPageIcon,
  channelPageLabel,
} from "@posthog/ui/features/canvas/components/channelPages";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useMarkChannelSeen } from "@posthog/ui/features/canvas/hooks/useMarkChannelSeen";
import { Text } from "@radix-ui/themes";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import type { ReactNode } from "react";

// The shared channel header. Every space scene renders the same breadcrumb —
// the root segment is identical whether or not there's a leaf, so the space
// name doesn't change size between the space home and its sub-pages. The new
// layout drops the section tab strip (the channel sidebar carries those
// entries); flag off keeps it. Starring lives on the sidebar back row and the
// channel list, not here.
export function ChannelHeader({
  channelId,
  page,
  leaf,
}: {
  channelId: string;
  /**
   * Which space page this is — supplies the leaf's label and icon. Every space
   * page names itself, the feed included ("{space} / Feed"); omitting it leaves
   * the root segment alone, for scenes that carry no page of their own.
   */
  page?: ChannelPageKey;
  /**
   * A document inside `page`, e.g. "{space} / Context / CONTEXT.md". The page
   * moves to the middle segment and links back to itself, so the way out of
   * the document is always in the header.
   */
  leaf?: { icon?: ReactNode; label: string };
}) {
  const channelsLayout = useChannelsLayout();
  const navigate = useNavigate();
  const { channels } = useChannels();
  const channelName = channels.find((c) => c.id === channelId)?.name;
  // Every channel surface renders this header, so mark the channel read here.
  useMarkChannelSeen(channelId);

  // Channels-layout off keeps the header it has always had: the channel pill
  // plus the section tab strip, no breadcrumb. Delete this branch when the
  // layout flag graduates.
  if (!channelsLayout) return <LegacyChannelHeader channelId={channelId} />;

  const pageSegment = page
    ? {
        icon: channelPageIcon(page, { size: 12 }),
        label: channelPageLabel(page),
      }
    : undefined;

  if (leaf && page && pageSegment) {
    return (
      <ChannelBreadcrumb
        channelName={channelName ?? "Space"}
        channelId={channelId}
        middle={{
          ...pageSegment,
          onClick: () =>
            void navigate({
              to: channelPageRoute(page),
              params: { channelId },
            }),
        }}
        leafIcon={leaf.icon}
        leafLabel={leaf.label}
      />
    );
  }

  return (
    <ChannelBreadcrumb
      channelName={channelName ?? "Space"}
      channelId={channelId}
      leafIcon={pageSegment?.icon}
      leafLabel={pageSegment?.label}
    />
  );
}

function channelPageRoute(page: ChannelPageKey) {
  switch (page) {
    case "home":
      return "/spaces/$channelId" as const;
    case "context":
      return "/spaces/$channelId/context" as const;
    case "loops":
      return "/spaces/$channelId/loops" as const;
    case "canvases":
      return "/spaces/$channelId/canvases" as const;
    case "history":
      return "/spaces/$channelId/history" as const;
    case "settings":
      return "/spaces/$channelId/settings" as const;
  }
}

function LegacyChannelHeader({ channelId }: { channelId: string }) {
  const navigate = useNavigate();
  const { channels } = useChannels();
  const channelName = channels.find((c) => c.id === channelId)?.name;
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const isHome = pathname === `/spaces/${channelId}`;

  return (
    <div className="flex min-w-0 items-center gap-2">
      <Button
        type="button"
        data-selected={isHome || undefined}
        onClick={() =>
          void navigate({ to: "/spaces/$channelId", params: { channelId } })
        }
        size="sm"
        className={cn("min-w-0", isHome ? "bg-fill-selected" : "")}
      >
        {channelGlyph(channelName, {
          size: 20,
          space: false,
          className: "shrink-0 text-muted-foreground/80",
        })}
        <Text className="min-w-0 truncate font-medium" title={channelName}>
          {channelName ?? "Channel"}
        </Text>
      </Button>
      <ChannelTabs channelId={channelId} />
    </div>
  );
}
