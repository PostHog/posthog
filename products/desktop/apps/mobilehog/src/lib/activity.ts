import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { toTaskActivityItems } from "@posthog/core/canvas/taskActivity";
import { formatRelativeAge, getRelativeDateGroup } from "@posthog/shared";
import type {
  TaskActivity,
  TaskActivityPage,
} from "@posthog/shared/domain-types";
import {
  type InfiniteData,
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { Alert } from "react-native";
import { useAuth } from "@/lib/auth";
import { getClient } from "@/lib/client";

export const activityKey = ["activity"] as const;

export function useActivity() {
  const session = useAuth((s) => s.session);
  return useInfiniteQuery({
    queryKey: activityKey,
    initialPageParam: undefined as
      | { before: string; beforeId: string }
      | undefined,
    queryFn: ({ pageParam }) => getClient().getTaskActivity(pageParam),
    getNextPageParam: (page) =>
      page.next_before && page.next_before_id
        ? { before: page.next_before, beforeId: page.next_before_id }
        : undefined,
    select: (data): TaskActivityPage => ({
      ...data.pages[0],
      results: data.pages.flatMap((page) => page.results),
    }),
    enabled: !!session,
    refetchInterval: 30_000,
  });
}

export function useMarkActivityRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (items: TaskActivityItem[]) => {
      const client = getClient();
      for (let offset = 0; offset < items.length; offset += 500) {
        await client.markTaskActivityRead(
          items.slice(offset, offset + 500).map((item) => ({
            task_id: item.taskId,
            seen_before: item.activityAt,
            ...(item.commentId ? { activity_id: item.id } : {}),
          })),
        );
      }
    },
    onMutate: async (items) => {
      await queryClient.cancelQueries({ queryKey: activityKey });
      const changed: TaskActivity[] = [];
      queryClient.setQueryData<InfiniteData<TaskActivityPage>>(
        activityKey,
        (data) => {
          if (!data) return data;
          const pages = data.pages.map((page) => ({
            ...page,
            results: page.results.map((row) => {
              const matches = items.some((item) =>
                item.commentId
                  ? item.id === row.id
                  : !row.latest_comment_id &&
                    item.taskId === row.task_id &&
                    Date.parse(row.activity_at) <= Date.parse(item.activityAt),
              );
              if (!row.is_unread || !matches) return row;
              changed.push(row);
              return { ...row, is_unread: false };
            }),
          }));
          return {
            ...data,
            pages: pages.map((page) => ({
              ...page,
              unread_count: Math.max(0, page.unread_count - changed.length),
            })),
          };
        },
      );
      return { changed };
    },
    onError: (_error, _items, context) => {
      queryClient.setQueryData<InfiniteData<TaskActivityPage>>(
        activityKey,
        (data) => {
          if (!data || !context) return data;
          let restored = 0;
          const pages = data.pages.map((page) => ({
            ...page,
            results: page.results.map((row) => {
              if (
                !row.is_unread &&
                context.changed.some(
                  (old) =>
                    old.id === row.id && old.activity_at === row.activity_at,
                )
              ) {
                restored++;
                return { ...row, is_unread: true };
              }
              return row;
            }),
          }));
          return {
            ...data,
            pages: pages.map((page) => ({
              ...page,
              unread_count: page.unread_count + restored,
            })),
          };
        },
      );
      Alert.alert(
        "Could not mark activity as read",
        "Check your connection and try again.",
      );
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: activityKey }),
  });
}

export type AgentIcon = "chat" | "check" | "question" | null;

export interface ActivityRow {
  item: TaskActivityItem;
  icon: AgentIcon;
  initials: string | null;
  metadata: string;
}

function authorName(item: TaskActivityItem): string {
  const author = item.author;
  if (!author) return "Someone";
  return author.first_name || author.email || "Someone";
}

// Mirrors desktop's activityPresentation: who did what, and which glyph.
function describe(
  item: TaskActivityItem,
  currentEmail?: string | null,
): { action: string; icon: AgentIcon } {
  switch (item.activityKind) {
    case "awaiting_input":
      return { action: "Agent is waiting for your reply", icon: "question" };
    case "completed":
      return { action: "Agent finished", icon: "check" };
    case "message":
      if (!item.author) return { action: "Agent replied", icon: "chat" };
      return {
        action:
          item.author.email === currentEmail
            ? "You replied"
            : `${authorName(item)} replied`,
        icon: null,
      };
    case "mention":
      return { action: `${authorName(item)} mentioned you`, icon: null };
    case "thread_reply":
      return { action: `${authorName(item)} replied to a thread`, icon: null };
    case "owned_item_comment":
      return {
        action: `${authorName(item)} commented on your task`,
        icon: null,
      };
    case "created":
      return { action: "You created", icon: null };
    default:
      return { action: "Activity", icon: null };
  }
}

export function toRows(
  page: TaskActivityPage | undefined,
  currentEmail?: string | null,
  currentName?: string | null,
): ActivityRow[] {
  if (!page) return [];
  return toTaskActivityItems(page.results).map((item) => {
    const { action, icon } = describe(item, currentEmail);
    return {
      item,
      icon,
      initials: icon
        ? null
        : (item.author?.first_name ?? currentName ?? "You")
            .slice(0, 2)
            .toUpperCase(),
      metadata: `${formatRelativeAge(item.activityAt)} · ${action}`,
    };
  });
}

export function groupByDay(
  rows: ActivityRow[],
): Array<{ label: string; rows: ActivityRow[] }> {
  const groups: Array<{ label: string; rows: ActivityRow[] }> = [];
  for (const row of rows) {
    const label = getRelativeDateGroup(row.item.activityAt) ?? "Today";
    const last = groups[groups.length - 1];
    if (last?.label === label) last.rows.push(row);
    else groups.push({ label, rows: [row] });
  }
  return groups;
}
