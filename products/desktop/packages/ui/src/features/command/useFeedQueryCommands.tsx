import { ArrowRightIcon, MagnifyingGlassIcon } from "@phosphor-icons/react";
import { UNTITLED_CANVAS_NAME } from "@posthog/core/canvas/canvasNaming";
import { channelDisplayLabel } from "@posthog/core/canvas/channelName";
import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import {
  type FeedQueryToken,
  feedQueryTypeScope,
  type ParsedFeedQuery,
  parseFeedQuery,
  type TypeValue,
} from "@posthog/core/tasks/feedQuery";
import { singleLineTitle } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import { useFeedQuerySuggestions } from "@posthog/ui/features/canvas/components/feedQuerySuggestions";
import { applyFeedQuerySuggestion } from "@posthog/ui/features/canvas/components/feedQuerySuggestionUtils";
import { useCanvasQueryResults } from "@posthog/ui/features/canvas/hooks/useCanvasQueryResults";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useProjectTaskFeeds } from "@posthog/ui/features/canvas/hooks/useProjectTaskFeeds";
import { useTaskFeedResults } from "@posthog/ui/features/canvas/hooks/useTaskFeedResults";
import type {
  Command,
  CommandSection,
} from "@posthog/ui/features/command/commandRow";
import {
  canvasRowParts,
  taskRowParts,
} from "@posthog/ui/features/command/commandRowFacts";
import { canvasHref } from "@posthog/ui/features/command/commandRowHref";
import { commandRowMeta } from "@posthog/ui/features/command/commandRowMeta";
import { TaskCommandIcon } from "@posthog/ui/features/command/TaskCommandIcon";
import { closeSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { useDebouncedValue } from "@posthog/ui/primitives/hooks/useDebouncedValue";
import {
  navigateToChannelDashboard,
  navigateToFeed,
} from "@posthog/ui/router/navigationBridge";
import { openTask } from "@posthog/ui/router/useOpenTask";
import { useMemo } from "react";

const FEED_QUERY_DEBOUNCE_MS = 300;

export type PaletteMode =
  | "browsing"
  | "completingKey"
  | "completingValue"
  | "querying";

export type MatchNoun = "task" | "canvas";

const MATCH_NOUN_PLURALS: Record<MatchNoun, string> = {
  task: "tasks",
  canvas: "canvases",
};

export function matchSummary(
  matchCount: number | null,
  shownCount: number,
  hasRepairs = false,
  noun: MatchNoun = "task",
): string {
  const plural = MATCH_NOUN_PLURALS[noun];
  if (matchCount == null) return "Searching…";
  if (matchCount === 0) {
    return hasRepairs
      ? `No ${plural} match this query.`
      : `No ${plural} match this query. Remove a filter to see more ${plural}.`;
  }
  if (matchCount > shownCount) {
    return `Showing ${shownCount} of ${matchCount} matching ${plural}.`;
  }
  return `${matchCount} matching ${matchCount === 1 ? noun : plural}`;
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
  matchNoun: MatchNoun;
  matchCount: number | null;
  partialResults: boolean;
  shownCount: number;
  hasRepairs: boolean;
  searchText: string;
}

function isQueryFilter(token: FeedQueryToken): boolean {
  return token.key !== "type" && token.key !== "saved";
}

/** What a query lists: canvases for `type:canvas`, tasks for a task filter, or nothing. */
function queryResultKind(parsed: ParsedFeedQuery): MatchNoun | null {
  const scope = feedQueryTypeScope(parsed);
  if (scope === "canvas") return "canvas";
  // The planner ignores `type:` and `saved:`, so neither can activate task-query mode.
  return scope === "task" || parsed.tokens.some(isQueryFilter) ? "task" : null;
}

function taskCommand(
  task: Task,
  spaceName: string | undefined,
  keywords: string,
): Command {
  return {
    id: `feed-query-task-${task.id}`,
    label: singleLineTitle(task.title),
    subtitle: commandRowMeta(taskRowParts(task)),
    detail: spaceName ? channelDisplayLabel(spaceName) : undefined,
    detailPrefix: "",
    keywords,
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
}

function canvasCommand(
  canvas: DashboardRecord,
  spaceName: string | undefined,
  keywords: string,
): Command {
  return {
    id: `feed-query-canvas-${canvas.id}`,
    label: singleLineTitle(canvas.name) || UNTITLED_CANVAS_NAME,
    subtitle: commandRowMeta(canvasRowParts(canvas)),
    detail: spaceName ? channelDisplayLabel(spaceName) : undefined,
    detailPrefix: "",
    keywords,
    icon: iconForTemplate(canvas.templateId, { size: 12 }),
    href: canvasHref(canvas.channelId, canvas.id),
    action: "open-canvas",
    channelId: canvas.channelId,
    onRun: () => {
      closeSettings();
      navigateToChannelDashboard(canvas.channelId, canvas.id);
    },
  };
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
  const resultKind = enabled ? queryResultKind(parsed) : null;
  const runsQuery = resultKind !== null;
  // Saved searches are task feeds, so only a task query has filters to save.
  const hasFilterTokens =
    resultKind === "task" && parsed.tokens.some(isQueryFilter);
  const searchText = enabled ? parsed.text : query;

  const { group, context } = useFeedQuerySuggestions(query, caret, {
    includeType: true,
  });

  const { debounced: previewQuery, isPending } = useDebouncedValue(
    runsQuery ? trimmed : "",
    FEED_QUERY_DEBOUNCE_MS,
  );
  const previewParsed = useMemo(
    () => parseFeedQuery(previewQuery),
    [previewQuery],
  );
  // Route on the debounced text, so each list only ever receives its own kind
  // of query. `isPending` covers the gap while the two kinds disagree.
  const previewKind = queryResultKind(previewParsed);
  const results = useTaskFeedResults(
    previewKind === "task" ? previewQuery : "",
  );
  const canvasResults = useCanvasQueryResults(
    previewKind === "canvas" ? previewQuery : "",
  );
  const counting =
    isPending ||
    (previewKind === "canvas" ? canvasResults.isLoading : results.isLoading);
  // The canvas list loads in one request, so it is never partial.
  const resultsComplete = previewKind === "canvas" || results.isComplete;
  const feeds = useProjectTaskFeeds();
  const { channels } = useChannels();

  const partialResults = runsQuery && !counting && !resultsComplete;
  const noMatches =
    resultKind === "task" &&
    !counting &&
    results.isComplete &&
    results.tasks.length === 0;
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

  const matchNoun = previewKind ?? resultKind ?? "task";
  const resultRows = useMemo(() => {
    if (!runsQuery) return [];
    const keywords = `${query} ${searchText}`;
    return previewKind === "canvas"
      ? canvasResults.canvases.map((canvas) =>
          canvasCommand(canvas, channelNames.get(canvas.channelId), keywords),
        )
      : results.tasks.map((task) =>
          taskCommand(
            task,
            task.channel ? channelNames.get(task.channel) : undefined,
            keywords,
          ),
        );
  }, [
    runsQuery,
    query,
    searchText,
    previewKind,
    canvasResults.canvases,
    results.tasks,
    channelNames,
  ]);

  return useMemo(() => {
    if (!enabled) {
      return {
        sections: [],
        keyChips: [],
        mode,
        scope: null,
        hasFilterTokens: false,
        matchNoun,
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
            icon: (
              <ArrowRightIcon size={12} className="text-muted-foreground" />
            ),
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
      runsQuery && !counting && resultsComplete ? resultRows.length : null;
    const shown = resultRows.slice(0, limit);
    if (shown.length > 0) {
      const items = [...shown];
      if (matchCount != null && matchCount > shown.length) {
        items.push({
          id: "feed-query-show-all",
          label: `Show all ${matchCount} matches`,
          icon: (
            <MagnifyingGlassIcon size={12} className="text-muted-foreground" />
          ),
          action: "show-all-matches",
          keepOpen: true,
          onRun: onShowAll,
        });
      }
      sections.push({
        label: `Matching ${MATCH_NOUN_PLURALS[matchNoun]}`,
        items,
      });
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
          icon: (
            <MagnifyingGlassIcon size={12} className="text-muted-foreground" />
          ),
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
      matchNoun,
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
    matchNoun,
    runsQuery,
    counting,
    resultsComplete,
    resultRows,
    partialResults,
    savedHits,
    limit,
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
