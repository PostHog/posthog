import { StarIcon } from "@phosphor-icons/react";
import {
  Button,
  cn,
  Skeleton,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { LOOPS_FLAG } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import { useChannelStarToggle } from "@posthog/ui/features/canvas/hooks/useChannelStars";
import {
  type Channel,
  useChannels,
} from "@posthog/ui/features/canvas/hooks/useChannels";
import { useMarkChannelSeen } from "@posthog/ui/features/canvas/hooks/useMarkChannelSeen";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { track } from "@posthog/ui/shell/analytics";
import { Link, useRouterState } from "@tanstack/react-router";
import type { ReactNode } from "react";

export type SpaceTab =
  | "context"
  | "activity"
  | "canvases"
  | "loops"
  | "settings";

const TABS: readonly { key: SpaceTab; label: string; segment: string }[] = [
  { key: "context", label: "Context", segment: "" },
  { key: "activity", label: "Activity", segment: "/activity" },
  { key: "canvases", label: "Canvases", segment: "/canvases" },
  { key: "loops", label: "Loops", segment: "/loops" },
  { key: "settings", label: "Settings", segment: "/settings" },
];

function SpaceStar({ channel }: { channel: Channel }) {
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
            className={cn(
              "text-muted-foreground",
              isStarred && "text-foreground",
            )}
            onClick={() => {
              track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
                action_type: isStarred ? "unstar" : "star",
                surface: "sidebar",
                channel_id: channel.id,
              });
              toggleStar();
            }}
          >
            <StarIcon size={14} weight={isStarred ? "fill" : "regular"} />
          </Button>
        }
      />
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

/**
 * The fixed part of every space page under the Work layout: the space's name
 * and star, then the tab strip. Identical on all five tabs, so only the
 * underline and the body change as you move between them. The chrome bar's
 * breadcrumb is cleared: the active tab is the page's name.
 */
export function SpaceTabbedPage({
  channelId,
  tab,
  children,
}: {
  channelId: string;
  tab: SpaceTab;
  children: ReactNode;
}) {
  const { channels, isLoading } = useChannels();
  const channel = channels.find((c) => c.id === channelId);
  const loopsEnabled = useFeatureFlag(LOOPS_FLAG);
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  useSetHeaderContent(null);
  useMarkChannelSeen(channelId);
  const tabs = loopsEnabled ? TABS : TABS.filter((t) => t.key !== "loops");
  const base = `/spaces/${channelId}`;

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col">
      <div className="shrink-0 border-border border-b px-5 pt-3">
        <div className="flex min-w-0 items-center gap-1.5">
          <span className="shrink-0 text-muted-foreground">
            {channelGlyph(channel?.name, {
              size: 16,
              space: true,
              personal: channel?.channelType === "personal",
              private: channel?.channelType === "private",
            })}
          </span>
          {channel ? (
            <span className="min-w-0 truncate font-semibold text-[15px]">
              {channel.name}
            </span>
          ) : isLoading ? (
            <Skeleton className="h-4 w-40" />
          ) : (
            <span className="font-semibold text-[15px]">Space</span>
          )}
          {channel && channel.channelType !== "personal" && (
            <SpaceStar channel={channel} />
          )}
        </div>
        <nav className="mt-1 flex items-center gap-4" aria-label="Space pages">
          {tabs.map((entry) => {
            const href = `${base}${entry.segment}`;
            const active =
              entry.key === tab ||
              (entry.key === "context" && pathname === `${base}/context`);
            return (
              <Link
                key={entry.key}
                to={href}
                data-selected={active || undefined}
                className={cn(
                  "-mb-px border-transparent border-b-2 px-0.5 pt-1 pb-2 text-[13px] text-muted-foreground no-underline transition-colors hover:text-foreground",
                  active && "border-foreground font-medium text-foreground",
                )}
              >
                {entry.label}
              </Link>
            );
          })}
        </nav>
      </div>
      <div className="min-h-0 min-w-0 flex-1">{children}</div>
    </div>
  );
}
