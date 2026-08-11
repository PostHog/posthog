import { BellIcon, XIcon } from "@phosphor-icons/react";
import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import {
  Button,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
  Tabs,
  TabsList,
  TabsTrigger,
} from "@posthog/quill";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { ActivityRow } from "@posthog/ui/features/canvas/components/ActivityView";
import { getVisibleActivityItems } from "@posthog/ui/features/canvas/components/activityFeed";
import { useBlockedTaskIds } from "@posthog/ui/features/canvas/hooks/useBlockedSessionCount";
import { useMarkTaskActivityRead } from "@posthog/ui/features/canvas/hooks/useMarkTaskActivityRead";
import { useTaskActivity } from "@posthog/ui/features/canvas/hooks/useTaskActivity";
import { useCommentsEnabled } from "@posthog/ui/features/sessions/useCommentsEnabled";
import { useCallback, useMemo, useState } from "react";
import { patchNavPanelSearch } from "../useNavPanels";

type ActivityFeedTab = "all" | "mentions" | "agents";

const FEED_TABS: readonly { key: ActivityFeedTab; label: string }[] = [
  { key: "all", label: "All" },
  { key: "mentions", label: "Mentions" },
  { key: "agents", label: "Agents" },
] as const;

function matchesTab(item: TaskActivityItem, tab: ActivityFeedTab): boolean {
  switch (tab) {
    case "mentions":
      return (
        item.activityKind === "mention" ||
        item.activityKind === "thread_reply" ||
        item.activityKind === "owned_item_comment"
      );
    case "agents":
      return (
        item.activityKind === "awaiting_input" ||
        item.activityKind === "completed" ||
        (item.activityKind === "message" && !item.author)
      );
    default:
      return true;
  }
}

/**
 * The Activity secondary panel: the cross-space feed as a compact list.
 * Opening a row loads that session in the content pane while the panel stays
 * put — the panel is the switcher, not a page.
 */
export function ActivityFeedPanel() {
  const commentsEnabled = useCommentsEnabled();
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const [tab, setTab] = useState<ActivityFeedTab>("all");

  const { items, isLoading, hasNextPage, isFetchingNextPage, fetchNextPage } =
    useTaskActivity();
  const blockedTaskIds = useBlockedTaskIds();
  const { mutate: markTasksRead } = useMarkTaskActivityRead();

  const shownItems = useMemo(
    () =>
      getVisibleActivityItems(items, commentsEnabled).filter((item) =>
        matchesTab(item, tab),
      ),
    [items, commentsEnabled, tab],
  );

  const markRead = useCallback(
    (item: TaskActivityItem) =>
      markTasksRead([
        {
          task_id: item.taskId,
          seen_before: item.activityAt,
          ...(item.commentId ? { activity_id: item.id } : {}),
        },
      ]),
    [markTasksRead],
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-10 shrink-0 items-center gap-1 pr-1 pl-3">
        <span className="min-w-0 flex-1 truncate font-medium text-[13px]">
          Activity
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
      <div className="flex h-[32px] shrink-0 items-center border-border border-b pl-2">
        <Tabs
          value={tab}
          onValueChange={(value: string) => setTab(value as ActivityFeedTab)}
        >
          <TabsList
            variant="line"
            aria-label="Activity filters"
            className="h-[31px] gap-0.5 p-0"
          >
            {FEED_TABS.map((t) => (
              <TabsTrigger key={t.key} value={t.key} className="px-2.5">
                <span className="font-medium text-[13px]">{t.label}</span>
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        {isLoading && shownItems.length === 0 ? (
          <div className="flex justify-center py-10">
            <Spinner />
          </div>
        ) : shownItems.length === 0 ? (
          <Empty className="border-0 py-6">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <BellIcon size={18} />
              </EmptyMedia>
              <EmptyTitle>No activity yet</EmptyTitle>
              <EmptyDescription>
                {tab === "all"
                  ? "Task updates and comments across spaces appear here."
                  : "Nothing here matches this filter yet."}
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <div className="flex flex-col gap-0.5">
            {shownItems.map((item) => (
              <ActivityRow
                key={item.id}
                item={item}
                channelId={item.channelId}
                onOpen={markRead}
                onMarkRead={markRead}
                currentUser={currentUser}
                blockedTaskIds={blockedTaskIds}
                surface="activity_panel"
                compact
              />
            ))}
          </div>
        )}
        {hasNextPage && (
          <div className="mt-3 flex justify-center">
            <Button
              variant="outline"
              size="sm"
              loading={isFetchingNextPage}
              disabled={isFetchingNextPage}
              onClick={() => void fetchNextPage()}
            >
              Load more
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
