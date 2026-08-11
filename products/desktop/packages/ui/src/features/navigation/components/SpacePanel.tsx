import { GearSixIcon, PackageIcon, XIcon } from "@phosphor-icons/react";
import {
  Button,
  cn,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Tabs,
  TabsList,
  TabsTrigger,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { LOOPS_FLAG } from "@posthog/shared";
import { ChannelSessionsList } from "@posthog/ui/features/canvas/components/ChannelSidebar";
import { ChannelsFab } from "@posthog/ui/features/canvas/components/ChannelsFab";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useDashboards } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useLoops } from "@posthog/ui/features/loops/hooks/useLoops";
import { SidebarItem } from "@posthog/ui/features/sidebar/components/SidebarItem";
import { LoopIcon } from "@posthog/ui/primitives/LoopIcon";
import { navigateToLoopDetail } from "@posthog/ui/router/navigationBridge";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useMemo } from "react";
import type { SpacePanelTab } from "../navPanelSearch";
import { patchNavPanelSearch, useNavPanelSearch } from "../useNavPanels";

function SpaceLoopsList({ channelId }: { channelId: string }) {
  const { data: loops } = useLoops();
  const spaceLoops = useMemo(
    () =>
      (loops ?? []).filter(
        (loop) => loop.context_target?.folder_id === channelId,
      ),
    [loops, channelId],
  );

  if (spaceLoops.length === 0) {
    return (
      <Empty className="border-0 py-6">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <LoopIcon size={18} />
          </EmptyMedia>
          <EmptyTitle>No loops yet</EmptyTitle>
          <EmptyDescription>
            Loops you create in this space show up here.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <div className="flex flex-col gap-px px-2 py-2">
      {spaceLoops.map((loop) => (
        <SidebarItem
          key={loop.id}
          depth={0}
          icon={<LoopIcon size={14} />}
          label={loop.name}
          isDimmed={!loop.enabled}
          onClick={() => navigateToLoopDetail(loop.id)}
        />
      ))}
    </div>
  );
}

function SpaceCanvasesList({ channelId }: { channelId: string }) {
  const navigate = useNavigate();
  const { dashboards } = useDashboards(channelId);

  if (dashboards.length === 0) {
    return (
      <Empty className="border-0 py-6">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <PackageIcon size={18} />
          </EmptyMedia>
          <EmptyTitle>No canvases yet</EmptyTitle>
          <EmptyDescription>
            Canvases made in this space show up here.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <div className="flex flex-col gap-px px-2 py-2">
      {dashboards.map((dashboard) => (
        <SidebarItem
          key={dashboard.id}
          depth={0}
          icon={iconForTemplate(dashboard.templateId ?? "", { size: 14 })}
          label={dashboard.name}
          onClick={() =>
            void navigate({
              to: "/website/$channelId/dashboards/$dashboardId",
              params: { channelId, dashboardId: dashboard.id },
            })
          }
        />
      ))}
    </div>
  );
}

const SPACE_TABS: readonly { key: SpacePanelTab; label: string }[] = [
  { key: "sessions", label: "Sessions" },
  { key: "loops", label: "Loops" },
  { key: "canvases", label: "Canvases" },
] as const;

/**
 * The secondary panel for a space: its sessions, loops, and canvases as
 * compact lists (click one, it opens in the content pane), with the gear
 * linking to the space's context/settings page.
 */
export function SpacePanel({ channelId }: { channelId: string }) {
  const navigate = useNavigate();
  const search = useNavPanelSearch();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const loopsEnabled = useFeatureFlag(LOOPS_FLAG, import.meta.env.DEV);

  const { channels } = useChannels();
  const channelName = channels.find((c) => c.id === channelId)?.name ?? "Space";

  const tabs = loopsEnabled
    ? SPACE_TABS
    : SPACE_TABS.filter((tab) => tab.key !== "loops");
  const tab = tabs.some((t) => t.key === search.stab)
    ? search.stab
    : "sessions";
  const onContextPage = pathname === `/website/${channelId}/context`;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-10 shrink-0 items-center gap-1 pr-1 pl-3">
        <span className="min-w-0 flex-1 truncate font-medium text-[13px]">
          {channelName}
        </span>
        <Button
          variant="default"
          size="icon-sm"
          aria-label="Close panel"
          onClick={() => patchNavPanelSearch({ panel: "off" })}
        >
          <XIcon size={14} />
        </Button>
      </div>
      <div className="flex h-[32px] shrink-0 items-center gap-1 border-border border-b pr-1 pl-2">
        <Tabs
          value={tab}
          onValueChange={(value: string) =>
            patchNavPanelSearch({ stab: value as SpacePanelTab })
          }
        >
          <TabsList
            variant="line"
            aria-label={`#${channelName}`}
            className="h-[31px] gap-0.5 p-0"
          >
            {tabs.map((t) => (
              <TabsTrigger key={t.key} value={t.key} className="px-1">
                <span className="font-medium text-[13px]">{t.label}</span>
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <div className="ml-auto flex shrink-0 items-center">
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  variant="default"
                  size="icon-sm"
                  aria-label="Space context"
                  data-selected={onContextPage || undefined}
                  className={cn(
                    "text-muted-foreground",
                    onContextPage && "bg-fill-selected text-foreground",
                  )}
                  onClick={() =>
                    void navigate({
                      to: "/website/$channelId/context",
                      params: { channelId },
                    })
                  }
                >
                  <GearSixIcon size={14} />
                </Button>
              }
            />
            <TooltipContent side="bottom">Context & settings</TooltipContent>
          </Tooltip>
        </div>
      </div>
      <div className="relative min-h-0 flex-1">
        {tab === "sessions" && (
          <>
            <ChannelSessionsList channelId={channelId} />
            <ChannelsFab channelId={channelId} />
          </>
        )}
        {tab === "loops" && (
          <div className="h-full overflow-y-auto">
            <SpaceLoopsList channelId={channelId} />
          </div>
        )}
        {tab === "canvases" && (
          <div className="h-full overflow-y-auto">
            <SpaceCanvasesList channelId={channelId} />
          </div>
        )}
      </div>
    </div>
  );
}
