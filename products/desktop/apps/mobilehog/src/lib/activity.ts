import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { toTaskActivityItems } from "@posthog/core/canvas/taskActivity";
import { formatRelativeAge, getRelativeDateGroup } from "@posthog/shared";
import type { TaskActivityPage } from "@posthog/shared/domain-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth";
import { getClient } from "@/lib/client";

export const activityKey = ["activity"] as const;

export function useActivity() {
  const session = useAuth((s) => s.session);
  return useQuery<TaskActivityPage>({
    queryKey: activityKey,
    queryFn: () => getClient().getTaskActivity(),
    enabled: !!session,
    refetchInterval: 30_000,
  });
}

export function useMarkActivityRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (item: TaskActivityItem) =>
      getClient().markTaskActivityRead([
        {
          task_id: item.taskId,
          seen_before: item.activityAt,
          activity_id: item.id,
        },
      ]),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: activityKey }),
  });
}

export type AgentIcon = "chat" | "check" | "question" | null;

export interface ActivityRow {
  item: TaskActivityItem;
  icon: AgentIcon;
  initials: string | null;
  metadata: string;
  space: string | null;
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
  const inSpace = !!item.channelName;
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
      return {
        action: inSpace ? "You created task in" : "You created",
        icon: null,
      };
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
    const space = item.channelName
      ? item.channelName === "personal"
        ? "Personal"
        : item.channelName
      : null;
    const suffix = space && !action.endsWith(" in") ? " in" : "";
    return {
      item,
      icon,
      initials: icon
        ? null
        : (item.author?.first_name ?? currentName ?? "You")
            .slice(0, 2)
            .toUpperCase(),
      metadata: `${formatRelativeAge(item.activityAt)} · ${action}${suffix}`,
      space,
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
