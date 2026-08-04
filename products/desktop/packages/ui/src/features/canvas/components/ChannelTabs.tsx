import { Button, cn, Tabs, TabsList, TabsTrigger } from "@posthog/quill";
import { LOOPS_FLAG } from "@posthog/shared";
import { CHANNEL_SECTIONS } from "@posthog/ui/features/canvas/channelSections";
import { ChannelPinnedMenu } from "@posthog/ui/features/canvas/components/ChannelPinnedMenu";
import {
  type ChannelPageKey,
  channelPageLabel,
} from "@posthog/ui/features/canvas/components/channelPages";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { Link, useNavigate, useRouterState } from "@tanstack/react-router";

const TABS = CHANNEL_SECTIONS.map((s) => ({
  key: s.key,
  label: s.label,
  to: `/website/$channelId/${s.key}` as const,
}));

// Home / History / Artifacts tab switcher shown in the legacy channel header
// bar, with a Pinned quick-access menu alongside. Pathname-driven active state
// (the codebase's convention) rather than Link's activeProps.
export function ChannelTabs({ channelId }: { channelId: string }) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const loopsEnabled = useFeatureFlag(LOOPS_FLAG, import.meta.env.DEV);
  const tabs = loopsEnabled ? TABS : TABS.filter((tab) => tab.key !== "loops");

  return (
    <nav className="flex items-center gap-px">
      {tabs.map((tab) => {
        const href = tab.to.replace("$channelId", channelId);
        const active = pathname === href;
        return (
          <Button
            key={tab.label}
            variant="default"
            size="sm"
            data-selected={active || undefined}
            className={cn(active && "bg-fill-selected")}
            render={<Link to={tab.to} params={{ channelId }} />}
          >
            {tab.label}
          </Button>
        );
      })}
      <ChannelPinnedMenu channelId={channelId} />
    </nav>
  );
}

// The space pages in the header's tab row: Feed leads (it's the space itself,
// and the way back once you've tabbed away), and labels come from the
// channelPages table ("Context", not the legacy "CONTEXT.md").
const PAGE_TAB_KEYS = [
  "home",
  "context",
  "loops",
  "artifacts",
  "history",
] as const satisfies readonly ChannelPageKey[];

/**
 * The channels-layout page switcher: quill line tabs under the space name,
 * matching the tab strips elsewhere (Inbox, Activity). Every space scene tells
 * the header which page it is, so the active tab is the `page` prop rather
 * than a pathname match. The Pinned quick-access menu keeps the row's right
 * edge.
 */
export function ChannelPageTabs({
  channelId,
  page,
}: {
  channelId: string;
  page?: ChannelPageKey;
}) {
  const navigate = useNavigate();
  const loopsEnabled = useFeatureFlag(LOOPS_FLAG, import.meta.env.DEV);
  const tabs = PAGE_TAB_KEYS.filter((key) => loopsEnabled || key !== "loops");

  return (
    <div className="flex min-w-0 items-center">
      <Tabs
        value={page ?? "home"}
        onValueChange={(value: string) => {
          if (value === "home") {
            void navigate({
              to: "/website/$channelId",
              params: { channelId },
            });
            return;
          }
          void navigate({
            to: `/website/$channelId/${value as Exclude<(typeof PAGE_TAB_KEYS)[number], "home">}`,
            params: { channelId },
          });
        }}
      >
        <TabsList
          variant="line"
          className="h-auto gap-0.5 [&_.quill-tabs__indicator]:transition-[transform,width]! [&_.quill-tabs__indicator]:duration-100! [&_.quill-tabs__indicator]:ease-out!"
        >
          {tabs.map((key) => (
            <TabsTrigger key={key} value={key} className="gap-1.5 px-2.5 py-2">
              <span className="font-medium text-[13px]">
                {channelPageLabel(key)}
              </span>
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      <span className="ml-auto">
        <ChannelPinnedMenu channelId={channelId} />
      </span>
    </div>
  );
}
