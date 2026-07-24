import { AtIcon, LinkIcon } from "@phosphor-icons/react";
import type { MentionActivityItem } from "@posthog/core/canvas/mentionActivity";
import {
  Button,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
} from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { MentionText } from "@posthog/ui/features/canvas/components/MentionText";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useMentionActivity } from "@posthog/ui/features/canvas/hooks/useMentionActivity";
import { normalizeChannelName } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useActivitySeenStore } from "@posthog/ui/features/canvas/stores/activitySeenStore";
import { copyChannelLink } from "@posthog/ui/features/canvas/utils/copyChannelLink";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import {
  navigateToChannelTask,
  navigateToTaskDetail,
} from "@posthog/ui/router/navigationBridge";
import { track } from "@posthog/ui/shell/analytics";
import { Text } from "@radix-ui/themes";
import { useEffect, useMemo, useState } from "react";

function ActivityRow({
  item,
  folderChannelId,
  isNew,
  currentUserEmail,
}: {
  item: MentionActivityItem;
  /** Desktop folder channel id (the /website route param); null when unmapped. */
  folderChannelId: string | null;
  /** Arrived since the viewer last opened this page. */
  isNew: boolean;
  currentUserEmail?: string | null;
}) {
  const openThread = () => {
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "open_mention",
      surface: "activity",
      channel_id: folderChannelId ?? undefined,
      task_id: item.taskId,
    });
    // The channel thread route is the deep-link target; tasks whose channel
    // folder is gone fall back to the plain task view.
    if (folderChannelId) {
      navigateToChannelTask(folderChannelId, item.taskId);
    } else {
      navigateToTaskDetail(item.taskId);
    }
  };

  return (
    <div className="group relative">
      <button
        type="button"
        onClick={openThread}
        className="flex w-full gap-2 rounded-md px-2 py-2 text-left hover:bg-fill-secondary"
      >
        <span className="relative mt-0.5 shrink-0">
          <UserAvatar user={item.author} size="xs" />
          {isNew && (
            <span
              className="-top-0.5 -right-0.5 absolute h-2 w-2 rounded-full bg-(--red-9)"
              title="New mention"
            />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2">
            <Text size="1" className="truncate">
              <Text as="span" size="1" weight="medium">
                {userDisplayName(item.author)}
              </Text>{" "}
              mentioned you
              {item.channelName && (
                <>
                  {" in "}
                  <Text as="span" size="1" weight="medium">
                    {item.channelName}
                  </Text>
                </>
              )}
            </Text>
            <Text size="1" className="shrink-0 text-muted-foreground">
              {formatRelativeTimeShort(item.createdAt)}
            </Text>
          </span>
          <Text size="1" className="block truncate text-muted-foreground">
            {item.taskTitle}
          </Text>
          <MentionText
            content={item.content}
            currentUserEmail={currentUserEmail}
            className="mt-1 block whitespace-pre-wrap break-words text-xs"
          />
        </span>
      </button>
      {folderChannelId && (
        <Button
          variant="default"
          size="icon-xs"
          aria-label="Copy thread link"
          className="absolute top-2 right-2 opacity-0 transition-opacity group-hover:opacity-100"
          onClick={() =>
            void copyChannelLink(folderChannelId, "activity", item.taskId)
          }
        >
          <LinkIcon size={14} />
        </Button>
      )}
    </div>
  );
}

// The Activity page: every channel-thread message that @-mentions the viewer,
// newest first. Opening it clears the sidebar badge.
export function ActivityView() {
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const { items, isLoading } = useMentionActivity();
  // Items carry backend channel names only; the desktop folder-channel id
  // (needed for /website navigation and copy-link) is resolved here, where
  // the single useChannels subscription lives.
  const { channels: folderChannels } = useChannels();
  const folderIdByName = useMemo(
    () =>
      new Map(
        folderChannels.map((folder) => [
          normalizeChannelName(folder.name),
          folder.id,
        ]),
      ),
    [folderChannels],
  );
  const folderChannelIdFor = (channelName: string | null): string | null =>
    channelName
      ? (folderIdByName.get(normalizeChannelName(channelName)) ?? null)
      : null;
  const markSeen = useActivitySeenStore((s) => s.markSeen);
  // Snapshot before marking seen so rows that were new on arrival keep their
  // dot for this visit.
  const [seenAtOpen] = useState(
    () => useActivitySeenStore.getState().lastSeenAt,
  );

  useEffect(() => {
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "view_activity",
      surface: "activity",
    });
  }, []);

  // Re-mark as items stream in so the badge stays cleared while reading.
  // biome-ignore lint/correctness/useExhaustiveDependencies: re-run per new item
  useEffect(() => {
    markSeen();
  }, [markSeen, items.length]);

  return (
    <div className="h-full overflow-y-auto bg-gray-1">
      <div className="mx-auto w-full max-w-[680px] px-4 py-6">
        <Text size="5" weight="bold" className="block">
          Activity
        </Text>
        <Text size="2" className="block text-muted-foreground">
          Mentions of you across channels.
        </Text>
        <div className="mt-4">
          {isLoading && items.length === 0 ? (
            <div className="flex justify-center py-16">
              <Spinner />
            </div>
          ) : items.length === 0 ? (
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <AtIcon size={20} />
                </EmptyMedia>
                <EmptyTitle>No mentions yet</EmptyTitle>
                <EmptyDescription>
                  When a teammate tags you with @ in a channel thread, it lands
                  here.
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <div className="flex flex-col gap-0.5">
              {items.map((item) => (
                <ActivityRow
                  key={item.messageId}
                  item={item}
                  folderChannelId={folderChannelIdFor(item.channelName)}
                  isNew={!seenAtOpen || item.createdAt > seenAtOpen}
                  currentUserEmail={currentUser?.email}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
