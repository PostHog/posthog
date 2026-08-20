import { ArrowRightIcon, MagnifyingGlassIcon } from "@phosphor-icons/react";
import {
  feedQueryTypeScope,
  parseFeedQuery,
  type TypeValue,
} from "@posthog/core/tasks/feedQuery";
import { formatRelativeTimeShort } from "@posthog/shared";
import { useFeedQuerySuggestions } from "@posthog/ui/features/canvas/components/feedQuerySuggestions";
import { applyFeedQuerySuggestion } from "@posthog/ui/features/canvas/components/feedQuerySuggestionUtils";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useProjectTaskFeeds } from "@posthog/ui/features/canvas/hooks/useProjectTaskFeeds";
import { useTaskFeedResults } from "@posthog/ui/features/canvas/hooks/useTaskFeedResults";
import { TaskCommandIcon } from "@posthog/ui/features/command/TaskCommandIcon";
import type {
  Command,
  CommandSection,
} from "@posthog/ui/features/command/useSearchSections";
import { closeSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { useDebouncedValue } from "@posthog/ui/primitives/hooks/useDebouncedValue";
import { navigateToFeed } from "@posthog/ui/router/navigationBridge";
import { openTask } from "@posthog/ui/router/useOpenTask";
import { useMemo } from "react";

const FEED_QUERY_DEBOUNCE_MS = 300;

export type PaletteMode =
  | "browsing"
  | "completingKey"
  | "completingValue"
  | "querying";

export function matchSummary(
  matchCount: number | null,
  shownCount: number,
  hasRepairs = false,
): string {
  if (matchCount == null) return "Searching…";
  if (matchCount === 0) {
    return hasRepairs
      ? "No tasks match this query."
      : "No tasks match this query. Remove a filter to see more tasks.";
  }
  if (matchCount > shownCount) {
    return `Showing ${shownCount} of ${matchCount} matching tasks.`;
  }
  return `${matchCount} ${matchCount === 1 ? "matching task" : "matching tasks"}`;
}

export interface FeedQueryKeyChip {
  label: string;
  hint?: string;
  apply: () => void;
}

export interface FeedQueryPalette {
  sections: CommandSection[];
  keyChips: FeedQueryKeyChip[];
  mode: PaletteMode;
  scope: TypeValue | null;
  hasFilterTokens: boolean;
  matchCount: number | null;
  partialResults: boolean;
  shownCount: number;
  hasRepairs: boolean;
  searchText: string;
}

export function useFeedQueryCommands({
  query,
  caret,
  enabled,
  limit,
  onApply,
  onShowAll,
}: {
  query: string;
  caret: number;
  enabled: boolean;
  limit: number;
  onApply: (next: string, caret: number) => void;
  onShowAll: () => void;
}): FeedQueryPalette {
  const trimmed = query.trim();
  const parsed = useMemo(() => parseFeedQuery(trimmed), [trimmed]);
  const scope = enabled ? feedQueryTypeScope(parsed) : null;
  // The planner ignores `type:` and `saved:`, so neither can activate task-query mode.
  const hasFilterTokens =
    enabled && parsed.tokens.some((t) => t.key !== "type" && t.key !== "saved");
  const searchText = enabled ? parsed.text : query;

  const { group, context } = useFeedQuerySuggestions(query, caret, {
    includeType: true,
  });

  const runsQuery = hasFilterTokens || scope === "task";
  const { debounced: previewQuery, isPending } = useDebouncedValue(
    enabled && runsQuery ? trimmed : "",
    FEED_QUERY_DEBOUNCE_MS,
  );
  const results = useTaskFeedResults(previewQuery);
  const counting = isPending || results.isLoading;
  const feeds = useProjectTaskFeeds();
  const { channels } = useChannels();

  const previewParsed = useMemo(
    () => parseFeedQuery(previewQuery),
    [previewQuery],
  );
  const partialResults = runsQuery && !counting && !results.isComplete;
  const noMatches =
    runsQuery && !counting && results.isComplete && results.tasks.length === 0;
  const splittable =
    noMatches && previewParsed.text !== "" && previewParsed.tokens.length > 0;
  const filtersOnlyQuery = splittable
    ? previewParsed.tokens.map((token) => token.raw).join(" ")
    : "";
  const textOnlyQuery = splittable ? previewParsed.text : "";
  const filtersOnly = useTaskFeedResults(filtersOnlyQuery);
  const textOnly = useTaskFeedResults(textOnlyQuery);

  const savedMode = context.activeKey === "saved";
  const savedHits = useMemo(() => {
    if (!enabled) return [];
    if (!savedMode && scope !== "saved") return [];
    const needle = (savedMode ? context.typed : searchText).toLowerCase();
    return feeds.filter(
      (feed) =>
        feed.name.toLowerCase().includes(needle) ||
        feed.query.toLowerCase().includes(needle),
    );
  }, [enabled, savedMode, scope, context.typed, searchText, feeds]);

  const keyMode = context.activeKey === null;
  const mode: PaletteMode = useMemo(() => {
    if (!enabled) return "browsing";
    if (!keyMode && (group.items.length > 0 || savedHits.length > 0)) {
      return "completingValue";
    }
    if (runsQuery) return "querying";
    if (context.typed !== "" && group.items.length > 0) return "completingKey";
    return "browsing";
  }, [
    enabled,
    keyMode,
    group.items.length,
    savedHits.length,
    runsQuery,
    context.typed,
  ]);

  const channelNames = useMemo(
    () => new Map(channels.map((channel) => [channel.id, channel.name])),
    [channels],
  );

  return useMemo(() => {
    if (!enabled) {
      return {
        sections: [],
        keyChips: [],
        mode,
        scope: null,
        hasFilterTokens: false,
        matchCount: null,
        partialResults: false,
        shownCount: 0,
        hasRepairs: false,
        searchText,
      };
    }
    const sections: CommandSection[] = [];

    const keyChips: FeedQueryKeyChip[] = keyMode
      ? group.items.map((suggestion) => ({
          label: suggestion.label,
          hint: suggestion.hint,
          apply: () => {
            const edit = applyFeedQuerySuggestion(query, context, suggestion);
            onApply(edit.next, edit.caret);
          },
        }))
      : [];

    if (!keyMode && group.items.length > 0) {
      sections.push({
        label: group.heading,
        items: group.items.map(
          (suggestion): Command => ({
            id: `feed-filter-${context.activeKey ?? "key"}-${suggestion.label}`,
            label: suggestion.label,
            detail: suggestion.hint,
            detailPrefix: "",
            keywords: `${query} ${searchText}`,
            icon: suggestion.icon,
            action: "complete-filter",
            keepOpen: true,
            shortcut: undefined,
            onRun: () => {
              const edit = applyFeedQuerySuggestion(query, context, suggestion);
              onApply(edit.next, edit.caret);
            },
          }),
        ),
      });
    }

    if (savedHits.length > 0) {
      sections.push({
        label: "Saved searches",
        items: savedHits.map(
          (feed): Command => ({
            id: `saved-search-${feed.id}`,
            label: feed.name,
            detail: feed.query,
            detailPrefix: "",
            keywords: `${query} ${searchText} ${feed.name}`,
            icon: <ArrowRightIcon size={12} className="text-gray-11" />,
            action: "open-feed",
            onRun: () => {
              closeSettings();
              navigateToFeed(feed.id);
            },
          }),
        ),
      });
    }

    const matchCount =
      runsQuery && !counting && results.isComplete
        ? results.tasks.length
        : null;
    const shown = runsQuery ? results.tasks.slice(0, limit) : [];
    if (shown.length > 0) {
      const items = shown.map((task): Command => {
        const space = task.channel ? channelNames.get(task.channel) : undefined;
        const subtitle = [
          task.repository ?? undefined,
          space ? `#${space}` : undefined,
          formatRelativeTimeShort(task.created_at),
        ]
          .filter(Boolean)
          .join(" · ");
        return {
          id: `feed-query-task-${task.id}`,
          label: task.title,
          subtitle,
          keywords: `${query} ${searchText}`,
          icon: <TaskCommandIcon task={task} />,
          action: "open-task",
          channelId: task.channel ?? undefined,
          onRun: () => {
            closeSettings();
            void openTask(
              task,
              task.channel ? { channelId: task.channel } : undefined,
            );
          },
        };
      });
      if (matchCount != null && matchCount > shown.length) {
        items.push({
          id: "feed-query-show-all",
          label: `Show all ${matchCount} matches`,
          icon: <MagnifyingGlassIcon size={12} className="text-gray-11" />,
          action: "show-all-matches",
          keepOpen: true,
          onRun: onShowAll,
        });
      }
      sections.push({ label: "Matching tasks", items });
    }

    let hasRepairs = false;
    if (splittable) {
      const repairs: Command[] = [];
      const addRepair = (
        id: string,
        label: string,
        count: number,
        next: string,
      ) => {
        if (count === 0) return;
        repairs.push({
          id,
          label,
          detail: `${count} ${count === 1 ? "task" : "tasks"}`,
          detailPrefix: "",
          icon: <MagnifyingGlassIcon size={12} className="text-gray-11" />,
          action: "repair-query",
          keepOpen: true,
          onRun: () => onApply(`${next} `, next.length + 1),
        });
      };
      addRepair(
        "feed-query-drop-text",
        `Search without "${previewParsed.text}"`,
        filtersOnly.tasks.length,
        filtersOnlyQuery,
      );
      addRepair(
        "feed-query-drop-filters",
        "Search without the filters",
        textOnly.tasks.length,
        textOnlyQuery,
      );
      if (repairs.length > 0) {
        hasRepairs = true;
        sections.push({ label: "Try instead", items: repairs });
      }
    }

    return {
      sections,
      keyChips,
      mode,
      scope,
      hasFilterTokens,
      matchCount,
      partialResults,
      shownCount: shown.length,
      hasRepairs,
      searchText,
    };
  }, [
    enabled,
    mode,
    group,
    context,
    keyMode,
    query,
    searchText,
    scope,
    hasFilterTokens,
    runsQuery,
    counting,
    results.isComplete,
    results.tasks,
    partialResults,
    savedHits,
    limit,
    channelNames,
    splittable,
    previewParsed.text,
    filtersOnly.tasks.length,
    filtersOnlyQuery,
    textOnly.tasks.length,
    textOnlyQuery,
    onApply,
    onShowAll,
  ]);
}
