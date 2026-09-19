import { StarIcon } from "@phosphor-icons/react";
import {
  Button,
  cn,
  Skeleton,
  Tabs,
  TabsList,
  TabsTrigger,
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
import {
  useChannelContextWikiPage,
  useContextWikiPage,
} from "@posthog/ui/features/context-wiki/hooks/useContextWiki";
import { useContextLayerFlag } from "@posthog/ui/features/feature-flags/useContextLayerFlag";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { track } from "@posthog/ui/shell/analytics";
import { useNavigate, useRouter } from "@tanstack/react-router";
import { type ReactNode, useEffect, useMemo } from "react";

export type SpaceTab =
  | "context"
  | "activity"
  | "canvases"
  | "loops"
  | "settings";

// Activity leads and owns the space's root: what happened here is what you
// came for, and context is what you check.
const TABS: readonly { key: SpaceTab; label: string; segment: string }[] = [
  { key: "activity", label: "Activity", segment: "" },
  { key: "context", label: "Context", segment: "/context" },
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
 * The inset every space tab's content starts at, so moving between tabs never
 * shifts the left edge under the reader.
 */
export const SPACE_TAB_INSET = "px-6";

/**
 * The fixed part of every space page under the Work layout: the space's name
 * in the app's own chrome bar — the same bar every other screen titles itself
 * in — and the tab strip under it. Identical on all five tabs, so only the
 * underline and the body change as you move between them.
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
  const navigate = useNavigate();
  const router = useRouter();
  const { channels, isLoading } = useChannels();
  const channel = channels.find((c) => c.id === channelId);
  const loopsEnabled = useFeatureFlag(LOOPS_FLAG);
  useMarkChannelSeen(channelId);
  // Both halves of the Context tab's read, held open for as long as the space
  // is. That tab's own lookups refetch on mount, so without a copy here the
  // first visit paints a spinner while two requests go out in sequence.
  const contextLayerEnabled = useContextLayerFlag();
  const contextPage = useChannelContextWikiPage(channelId, contextLayerEnabled);
  useContextWikiPage(contextPage.data?.path ?? "");
  const tabs = loopsEnabled ? TABS : TABS.filter((t) => t.key !== "loops");
  const base = `/spaces/${channelId}`;

  // Warm every sibling's route the moment the space opens. There are four of
  // them and each is split into its own chunk, so without this the first visit
  // to a tab pays for a fetch before it can paint.
  useEffect(() => {
    for (const entry of tabs) {
      void router.preloadRoute({ to: `${base}${entry.segment}` });
    }
  }, [base, router, tabs]);

  // The space's name goes where every other screen puts its title, rather than
  // into a header of this page's own invention.
  useSetHeaderContent(
    useMemo(
      () => (
        <div className="flex min-w-0 items-center gap-1.5">
          <span className="shrink-0 text-muted-foreground">
            {channelGlyph(channel?.name, {
              size: 14,
              space: true,
              personal: channel?.channelType === "personal",
              private: channel?.channelType === "private",
            })}
          </span>
          {channel ? (
            <span className="min-w-0 truncate font-medium text-[13px]">
              {channel.name}
            </span>
          ) : isLoading ? (
            <Skeleton className="h-3.5 w-40" />
          ) : (
            <span className="font-medium text-[13px]">Space</span>
          )}
          {channel && channel.channelType !== "personal" && (
            <SpaceStar channel={channel} />
          )}
        </div>
      ),
      [channel, isLoading],
    ),
  );

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col">
      <div className={cn("shrink-0 border-border border-b", SPACE_TAB_INSET)}>
        <Tabs
          value={tab}
          onValueChange={(value: string) => {
            const next = tabs.find((entry) => entry.key === value);
            if (next) void navigate({ to: `${base}${next.segment}` });
          }}
        >
          <TabsList variant="line" aria-label="Space pages">
            {tabs.map((entry) => (
              <TabsTrigger
                key={entry.key}
                value={entry.key}
                // Belt and braces for a tab added while the page is open.
                onPointerEnter={() => {
                  void router.preloadRoute({
                    to: `${base}${entry.segment}`,
                  });
                }}
              >
                {entry.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>
      <div className="min-h-0 min-w-0 flex-1">{children}</div>
    </div>
  );
}
