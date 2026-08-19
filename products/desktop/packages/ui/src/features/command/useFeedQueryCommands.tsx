import { MagnifyingGlassIcon } from "@phosphor-icons/react";
import {
  feedQueryTypeScope,
  parseFeedQuery,
  type TypeValue,
} from "@posthog/core/tasks/feedQuery";
import {
  applyFeedQuerySuggestion,
  useFeedQuerySuggestions,
} from "@posthog/ui/features/canvas/components/feedQuerySuggestions";
import { useTaskFeedResults } from "@posthog/ui/features/canvas/hooks/useTaskFeedResults";
import { useTaskFeedsStore } from "@posthog/ui/features/canvas/stores/taskFeedsStore";
import type {
  Command,
  CommandSection,
} from "@posthog/ui/features/command/useSearchSections";
import { closeSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { useDebouncedValue } from "@posthog/ui/primitives/hooks/useDebouncedValue";
import { navigateToFeed } from "@posthog/ui/router/navigationBridge";
import { openTask } from "@posthog/ui/router/useOpenTask";
import { FileTextIcon } from "@radix-ui/react-icons";
import { useMemo } from "react";

/** How many matching tasks the palette shows before deferring to the feed. */
const MAX_FEED_QUERY_RESULTS = 8;
const FEED_QUERY_DEBOUNCE_MS = 300;

/** A filter-key chip for the strip under the palette input. */
export interface FeedQueryKeyChip {
  label: string;
  hint?: string;
  apply: () => void;
}

export interface FeedQueryPalette {
  /** Value completions for the token under the caret, save-as-feed, and the
   * query's matching tasks — the sections that lead the palette list. */
  sections: CommandSection[];
  /**
   * Filter keys the caret's bare word could start, for the one-line chip
   * strip. Kept out of the list on purpose: twelve key rows buried the
   * results (the thing being searched), where a chip strip costs one line.
   */
  keyChips: FeedQueryKeyChip[];
  /** What `type:` scopes the results to, or null for everything. */
  scope: TypeValue | null;
  /** The query carries a filter beyond `type:` — the palette is a feed query. */
  hasFilterTokens: boolean;
  /** What the query matches right now, or null while it is still counting. */
  matchCount: number | null;
  /** The free-text words, for matching commands/spaces instead of the raw
   * query (whose tokens would never substring-match a label). */
  searchText: string;
}

/**
 * The command palette's query brain — always on, not a mode. Every keystroke
 * gets completions for the chunk under the caret (filter keys while typing a
 * bare word, a key's values inside a token) folded into the palette list as
 * its leading section; a query carrying a real filter also gets "Save as
 * feed" and its matching tasks. Plain text contributes nothing beyond
 * `searchText`, so ordinary command searching stays exactly as it was.
 */
export function useFeedQueryCommands({
  query,
  caret,
  enabled,
  onApply,
}: {
  query: string;
  /** The palette input's caret, for chunk-of-interest completion. */
  caret: number;
  /** Feeds are a spaces-layout feature; off it this contributes nothing. */
  enabled: boolean;
  /** Replace the palette query after a completion, placing the caret. */
  onApply: (next: string, caret: number) => void;
}): FeedQueryPalette {
  const trimmed = query.trim();
  const parsed = useMemo(() => parseFeedQuery(trimmed), [trimmed]);
  const scope = enabled ? feedQueryTypeScope(parsed) : null;
  const hasFilterTokens =
    enabled && parsed.tokens.some((t) => t.key !== "type");
  const searchText = enabled ? parsed.text : query;

  const { group, context } = useFeedQuerySuggestions(query, caret, {
    includeType: true,
  });

  // The task query runs whenever it filters something: real tokens, or a
  // type:task scope narrowing by text. Debounced so keystrokes don't each
  // become a round of list requests.
  const runsQuery = hasFilterTokens || scope === "task";
  const { debounced: previewQuery, isPending } = useDebouncedValue(
    enabled && runsQuery ? trimmed : "",
    FEED_QUERY_DEBOUNCE_MS,
  );
  const results = useTaskFeedResults(previewQuery);
  const counting = isPending || results.isLoading;
  const feeds = useTaskFeedsStore((state) => state.feeds);

  return useMemo(() => {
    if (!enabled) {
      return {
        sections: [],
        keyChips: [],
        scope: null,
        hasFilterTokens: false,
        matchCount: null,
        searchText,
      };
    }
    const sections: CommandSection[] = [];

    // Key suggestions become chips; a key's values stay list rows — they are
    // the thing being chosen mid-token, and there are only ever a few.
    const keyMode = context.activeKey === null;
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

    // `saved:` opens a saved search (as does a `type:saved` scope): the rows
    // navigate to the search's page rather than completing a token.
    const savedMode = context.activeKey === "saved";
    if (savedMode || scope === "saved") {
      const needle = (savedMode ? context.typed : searchText).toLowerCase();
      const hits = feeds.filter(
        (feed) =>
          feed.name.toLowerCase().includes(needle) ||
          feed.query.toLowerCase().includes(needle),
      );
      if (hits.length > 0) {
        sections.push({
          label: "Saved searches",
          items: hits.map(
            (feed): Command => ({
              id: `saved-search-${feed.id}`,
              label: feed.name,
              detail: feed.query,
              detailPrefix: "",
              keywords: `${query} ${searchText} ${feed.name}`,
              icon: <MagnifyingGlassIcon size={12} className="text-gray-11" />,
              action: "open-feed",
              onRun: () => {
                closeSettings();
                navigateToFeed(feed.id);
              },
            }),
          ),
        });
      }
    }

    if (runsQuery && results.tasks.length > 0) {
      sections.push({
        label: "Matching tasks",
        items: results.tasks.slice(0, MAX_FEED_QUERY_RESULTS).map(
          (task): Command => ({
            id: `feed-query-task-${task.id}`,
            label: task.title,
            detail: task.repository ?? undefined,
            detailPrefix: "",
            keywords: `${query} ${searchText}`,
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
          }),
        ),
      });
    }

    return {
      sections,
      keyChips,
      scope,
      hasFilterTokens,
      matchCount: runsQuery && !counting ? results.tasks.length : null,
      searchText,
    };
  }, [
    enabled,
    group,
    context,
    query,
    searchText,
    scope,
    hasFilterTokens,
    runsQuery,
    counting,
    results.tasks,
    feeds,
    onApply,
  ]);
}
