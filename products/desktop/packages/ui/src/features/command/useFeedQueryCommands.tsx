import { MagnifyingGlassIcon } from "@phosphor-icons/react";
import { parseFeedQuery } from "@posthog/core/tasks/feedQuery";
import { useTaskFeedResults } from "@posthog/ui/features/canvas/hooks/useTaskFeedResults";
import type {
  Command,
  CommandSection,
} from "@posthog/ui/features/command/useSearchSections";
import { closeSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { useDebouncedValue } from "@posthog/ui/primitives/hooks/useDebouncedValue";
import { openTask } from "@posthog/ui/router/useOpenTask";
import { FileTextIcon } from "@radix-ui/react-icons";
import { useMemo } from "react";

/** How many matching tasks the palette shows before deferring to the feed. */
const MAX_FEED_QUERY_RESULTS = 8;
const FEED_QUERY_DEBOUNCE_MS = 300;

/**
 * The command palette's feed-query mode. The moment the typed text carries a
 * filter token (`created-by:@me`, `status:failed`, …) it is a query, not a
 * command lookup — so the palette runs it live, lists the matching tasks, and
 * leads with "Save as feed", which hands the query to the feed modal. Plain
 * text stays the ordinary command/task search.
 */
export function useFeedQueryCommands({
  query,
  enabled,
  onSaveAsFeed,
}: {
  query: string;
  /** Feeds are a spaces-layout feature; off it this contributes nothing. */
  enabled: boolean;
  /** Called with the query when "Save as feed" is picked. */
  onSaveAsFeed: (query: string) => void;
}): CommandSection[] {
  const trimmed = query.trim();
  const parsed = useMemo(() => parseFeedQuery(trimmed), [trimmed]);
  const isFeedQuery = enabled && parsed.tokens.length > 0;

  // Debounced so each keystroke doesn't become a round of list requests.
  const { debounced: previewQuery, isPending } = useDebouncedValue(
    isFeedQuery ? trimmed : "",
    FEED_QUERY_DEBOUNCE_MS,
  );
  const results = useTaskFeedResults(previewQuery);
  const counting = isPending || results.isLoading;

  return useMemo(() => {
    if (!isFeedQuery) return [];

    // Every item carries the raw query as keywords, or the palette's own
    // text filter would drop rows whose labels don't contain the query.
    const save: Command = {
      id: "feed-query-save",
      label: "Save as feed…",
      detail: counting
        ? "running query"
        : `${results.tasks.length} ${results.tasks.length === 1 ? "task matches" : "tasks match"}`,
      detailPrefix: "",
      keywords: query,
      icon: <MagnifyingGlassIcon size={12} className="text-gray-11" />,
      action: "save-feed",
      onRun: () => {
        closeSettings();
        onSaveAsFeed(trimmed);
      },
    };

    const taskItems: Command[] = results.tasks
      .slice(0, MAX_FEED_QUERY_RESULTS)
      .map((task) => ({
        id: `feed-query-task-${task.id}`,
        label: task.title,
        detail: task.repository ?? undefined,
        detailPrefix: "",
        keywords: query,
        icon: <FileTextIcon className="h-3 w-3 text-gray-11" />,
        action: "open-task",
        channelId: task.channel ?? undefined,
        onRun: () => {
          closeSettings();
          void openTask(
            task,
            task.channel ? { channelId: task.channel } : undefined,
          );
        },
      }));

    return [
      { label: "Feed query", items: [save] },
      ...(taskItems.length > 0
        ? [{ label: "Matching tasks", items: taskItems }]
        : []),
    ];
  }, [isFeedQuery, counting, results.tasks, query, trimmed, onSaveAsFeed]);
}
