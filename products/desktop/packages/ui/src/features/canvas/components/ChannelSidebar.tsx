import {
  ChatsCircleIcon,
  PackageIcon,
  ShapesIcon,
} from "@phosphor-icons/react";
import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Tabs,
  TabsList,
  TabsTrigger,
} from "@posthog/quill";
import { LOOPS_FLAG } from "@posthog/shared";
import { ChannelBackRow } from "@posthog/ui/features/canvas/components/ChannelBackRow";
import { ChannelItemsPane } from "@posthog/ui/features/canvas/components/ChannelItemsPane";
import { ChannelsFab } from "@posthog/ui/features/canvas/components/ChannelsFab";
import {
  type ChannelPageKey,
  channelPageLabel,
} from "@posthog/ui/features/canvas/components/channelPages";
import { useChannelItems } from "@posthog/ui/features/canvas/hooks/useChannelItems";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { SidebarKbdHint } from "@posthog/ui/features/sidebar/components/items/SidebarKbdHint";
import { SidebarItem } from "@posthog/ui/features/sidebar/components/SidebarItem";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useMemo, useState } from "react";

const RECENTS_CAP = 30;

/** The list holds two kinds of thing, and shows one of them at a time. */
type ChannelTab = ChannelItemModel["kind"];

const CHANNEL_TABS: readonly {
  value: ChannelTab;
  label: string;
}[] = [
  { value: "task", label: "Sessions" },
  { value: "canvas", label: "Canvases" },
];

function ChannelTabs({
  tab,
  onTabChange,
}: {
  tab: ChannelTab;
  onTabChange: (tab: ChannelTab) => void;
}) {
  return (
    <Tabs
      value={tab}
      onValueChange={(value: string) => onTabChange(value as ChannelTab)}
      className="shrink-0"
    >
      {/* text-[13px] is the sidebar's own scale: quill's default tab is
          sized for a page header, which reads as a heading over this list. */}
      {/* quill-tabs-fill: the active/hover fills, from globals.css — they
          can't be utilities here, see the rule's comment. */}
      <TabsList
        variant="line"
        className="quill-tabs-fill h-auto gap-0.5 border-b-0"
      >
        {CHANNEL_TABS.map(({ value, label }) => (
          <TabsTrigger
            key={value}
            value={value}
            className="shrink-0 rounded-sm px-2 py-0.5 text-[13px]"
          >
            <span className="whitespace-nowrap">{label}</span>
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}

/** An empty tab says what would fill it, rather than what the space holds. */
function TabEmptyState({ tab }: { tab: ChannelTab }) {
  return (
    <Empty className="border-0 py-6">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          {tab === "canvas" ? (
            <ShapesIcon size={18} />
          ) : (
            <ChatsCircleIcon size={18} />
          )}
        </EmptyMedia>
        <EmptyTitle>
          {tab === "canvas" ? "No canvases yet" : "No sessions yet"}
        </EmptyTitle>
        <EmptyDescription>
          {tab === "canvas"
            ? "Canvases you create in this space show up here."
            : "Sessions you start in this space show up here."}
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
}

/**
 * The channel pane of the sidebar slider: the way back to the channel list,
 * the channel's sections, then its pinned and recent tasks & canvases.
 */
export function ChannelSidebar({ channelId }: { channelId: string }) {
  const navigate = useNavigate();
  // Only paths inside this space matter here. Collapsing the rest to "" keeps
  // every row still while the user is elsewhere (settings, another space).
  const pathname = useRouterState({
    select: (s) =>
      s.location.pathname.startsWith(`/spaces/${channelId}`)
        ? s.location.pathname
        : "",
  });
  const loopsEnabled = useFeatureFlag(LOOPS_FLAG);

  const { items, actions, isLoading, channelMissing } =
    useChannelItems(channelId);

  const [chosenTab, setChosenTab] = useState({
    channelId,
    tab: "task" as ChannelTab,
  });
  const tab = chosenTab.channelId === channelId ? chosenTab.tab : "task";
  const setTab = (next: ChannelTab) => setChosenTab({ channelId, tab: next });

  const { channels } = useChannels();
  // By type, not by name: the list relabels the personal channel on the way in,
  // so its name is no longer the backend's.
  const channel = channels.find((c) => c.id === channelId);
  const isPersonalChannel = channel?.channelType === "personal";
  // The tab is the list, so everything below it — the filters, the empty state,
  // the sections — is about one kind of thing at a time.
  const tabItems = useMemo(
    () => items.filter((item) => item.kind === tab),
    [items, tab],
  );

  const base = `/spaces/${channelId}`;
  // Activeness is a key comparison rather than a flag baked into each item, so
  // navigating doesn't rebuild the list.
  const activeKey = useMemo(() => {
    const dashboard = pathname.match(/\/dashboards\/([^/]+)$/);
    if (dashboard) return `canvas:${dashboard[1]}`;
    const task = pathname.match(/\/tasks\/([^/]+)$/);
    return task ? `task:${task[1]}` : null;
  }, [pathname]);

  // Label comes from the shared space-page table, so a sidebar row and the
  // header breadcrumb for the same page can never disagree. No icon: this is a
  // short list of words, and glyphs here only compete with the status dots
  // in the sessions list below for the eye's attention.
  const sectionRow = (
    page: ChannelPageKey,
    to: string,
    onClick: () => void,
  ) => (
    <SidebarItem
      depth={0}
      label={channelPageLabel(page)}
      isActive={pathname === to}
      onClick={onClick}
    />
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ChannelBackRow channelId={channelId} />

      <div className="flex flex-col gap-px px-2 pt-2">
        {/* Starting a session is what you came here to do, so it leads the
            pane's list of places rather than hiding behind one of them. */}
        <SidebarItem
          depth={0}
          label="New session"
          isActive={pathname === `${base}/new`}
          onClick={() =>
            void navigate({
              to: "/spaces/$channelId/new",
              params: { channelId },
            })
          }
          // ⌘N inside a space lands on this same route (openTaskInput scopes to
          // the channel you're in), so the row can claim the key.
          endHint={<SidebarKbdHint keys={SHORTCUTS.NEW_TASK} />}
        />
        {sectionRow(
          "home",
          base,
          () =>
            void navigate({ to: "/spaces/$channelId", params: { channelId } }),
        )}
        {sectionRow(
          "context",
          `${base}/context`,
          () =>
            void navigate({
              to: "/spaces/$channelId/context",
              params: { channelId },
            }),
        )}
        {loopsEnabled &&
          sectionRow(
            "loops",
            `${base}/loops`,
            () =>
              void navigate({
                to: "/spaces/$channelId/loops",
                params: { channelId },
              }),
          )}
      </div>

      <div className="mt-2 flex min-h-0 flex-1 flex-col">
        {channelMissing ? (
          <Empty className="border-0 py-6">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <PackageIcon size={18} />
              </EmptyMedia>
              <EmptyTitle>Space unavailable</EmptyTitle>
              <EmptyDescription>
                It may have been deleted, or belong to another project.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <ChannelItemsPane
            items={tabItems}
            isLoading={isLoading}
            actions={actions}
            activeKey={activeKey}
            surface="space"
            headerLeft={<ChannelTabs tab={tab} onTabChange={setTab} />}
            hasMultipleAuthors={!isPersonalChannel}
            hasRuns={tab === "task"}
            cap={RECENTS_CAP}
            channelIdFor={() => channelId}
            emptyState={<TabEmptyState tab={tab} />}
            overlay={<ChannelsFab channelId={channelId} />}
            searchLabel={
              tab === "canvas" ? "Search canvases" : "Search sessions"
            }
          />
        )}
      </div>
    </div>
  );
}
