import {
  Autocomplete,
  AutocompleteCollection,
  AutocompleteGroup,
  AutocompleteInput,
  AutocompleteItem,
  AutocompleteLabel,
  AutocompleteList,
  AutocompleteStatus,
  cn,
  Dialog,
  DialogContent,
  Kbd,
  KbdGroup,
} from "@posthog/quill";
import { LOOPS_FLAG, PROJECT_BLUEBIRD_FLAG } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { useTaskArchive } from "@posthog/ui/features/archive/useTaskArchive";
import {
  EDITOR_TEXT_CLASS,
  FeedQueryHighlight,
} from "@posthog/ui/features/canvas/components/FeedQueryInput";
import { TaskFeedModal } from "@posthog/ui/features/canvas/components/TaskFeedModal";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { CommandKeyHints } from "@posthog/ui/features/command/CommandKeyHints";
import {
  addRecentCommand,
  matchesCommandSearch,
  prioritizeExactCommandMatches,
} from "@posthog/ui/features/command/commandSearch";
import { useFileSearchStore } from "@posthog/ui/features/command/fileSearchStore";
import { formatHotkeyParts } from "@posthog/ui/features/command/keyboard-shortcuts";
import { PaletteFilterChips } from "@posthog/ui/features/command/PaletteFilterChips";
import {
  useOpenReviewPanel,
  useRemoteTaskSearch,
  useSystemPrefersDark,
} from "@posthog/ui/features/command/useCommandMenuRuntime";
import { useCommandMenuSections } from "@posthog/ui/features/command/useCommandMenuSections";
import {
  matchSummary,
  useFeedQueryCommands,
} from "@posthog/ui/features/command/useFeedQueryCommands";
import { useFileSearchContext } from "@posthog/ui/features/command/useFileSearchContext";
import {
  type Command,
  type CommandSection,
  useSearchSections,
} from "@posthog/ui/features/command/useSearchSections";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useInboxAvailable } from "@posthog/ui/features/feature-flags/useInboxAvailable";
import { useFeedbackStore } from "@posthog/ui/features/feedback/feedbackStore";
import { useFolders } from "@posthog/ui/features/folders/useFolders";
import { useProvisioningStore } from "@posthog/ui/features/provisioning/store";
import {
  closeSettings,
  openSettings,
} from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useSpendAnalysisEnabled } from "@posthog/ui/features/usage/useSpendAnalysisEnabled";
import { useWorkspaces } from "@posthog/ui/features/workspace/useWorkspace";
import { navigateToFeed } from "@posthog/ui/router/navigationBridge";
import { useAppView } from "@posthog/ui/router/useAppView";
import { track } from "@posthog/ui/shell/analytics";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import {
  lazy,
  type MutableRefObject,
  type KeyboardEvent as ReactKeyboardEvent,
  type RefObject,
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

interface CommandMenuProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

// Static-importing this pulls the task-creation stack onto the mod+K path.
const CreateChannelModalLazy = lazy(() =>
  import("@posthog/ui/features/canvas/components/CreateChannelModal").then(
    (module) => ({ default: module.CreateChannelModal }),
  ),
);

const DEFAULT_RESULT_LIMIT = 8;
const COLLAPSED_CHIP_COUNT = 5;

function PaletteQueryMirror({
  query,
  wrapRef,
  visible,
}: {
  query: string;
  wrapRef: React.RefObject<HTMLDivElement | null>;
  visible: boolean;
}) {
  const mirrorRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState<{
    left: number;
    top: number;
    width: number;
    height: number;
    padLeft: number;
    padRight: number;
  } | null>(null);

  // A child layout effect runs before the parent ref attaches.
  useEffect(() => {
    if (!visible) return;
    const wrap = wrapRef.current;
    const input = wrap?.querySelector("input");
    if (!wrap || !input) return;
    const measure = () => {
      const w = wrap.getBoundingClientRect();
      const r = input.getBoundingClientRect();
      const style = getComputedStyle(input);
      setBox({
        left: r.left - w.left,
        top: r.top - w.top,
        width: r.width,
        height: r.height,
        padLeft: Number.parseFloat(style.paddingLeft),
        padRight: Number.parseFloat(style.paddingRight),
      });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(input);
    const sync = () => {
      if (mirrorRef.current) mirrorRef.current.scrollLeft = input.scrollLeft;
    };
    input.addEventListener("scroll", sync);
    return () => {
      observer.disconnect();
      input.removeEventListener("scroll", sync);
    };
  }, [visible, wrapRef]);

  // A completion can change the input scroll position without a scroll event.
  useLayoutEffect(() => {
    const input = wrapRef.current?.querySelector("input");
    if (input && mirrorRef.current)
      mirrorRef.current.scrollLeft = input.scrollLeft;
  });

  if (!visible || !box) return null;
  return (
    <div
      ref={mirrorRef}
      aria-hidden
      className={cn(
        "pointer-events-none absolute z-10 flex items-center overflow-x-hidden",
        EDITOR_TEXT_CLASS,
      )}
      style={{
        left: box.left,
        top: box.top,
        width: box.width,
        height: box.height,
        paddingLeft: box.padLeft,
        paddingRight: box.padRight,
      }}
    >
      <FeedQueryHighlight query={query} />
    </div>
  );
}

interface CommandMenuDialogProps {
  bluebirdEnabled: boolean;
  feedQuery: ReturnType<typeof useFeedQueryCommands>;
  handleSelect: (id: string | null) => void;
  highlightedId: MutableRefObject<string | null>;
  inputWrapRef: RefObject<HTMLDivElement | null>;
  onInputKeyDown: (event: ReactKeyboardEvent<HTMLInputElement>) => void;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  paletteFilter: (command: { label: string; keywords?: string }) => boolean;
  query: string;
  sections: CommandSection[];
  setQuery: (query: string) => void;
  showMatchSummary: boolean;
  spacesLayout: boolean;
  trackCaret: () => void;
}

function CommandMenuDialog({
  bluebirdEnabled,
  feedQuery,
  handleSelect,
  highlightedId,
  inputWrapRef,
  onInputKeyDown,
  onOpenChange,
  open,
  paletteFilter,
  query,
  sections,
  setQuery,
  showMatchSummary,
  spacesLayout,
  trackCaret,
}: CommandMenuDialogProps) {
  const {
    hasFilterTokens,
    hasRepairs,
    keyChips,
    matchCount,
    mode,
    partialResults,
    shownCount,
  } = feedQuery;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="w-[720px] max-w-[90vw] gap-0 p-0"
        showCloseButton={false}
      >
        <Autocomplete<Command>
          inline
          defaultOpen
          items={sections}
          value={query}
          autoHighlight
          keepHighlight
          onItemHighlighted={(value) => {
            highlightedId.current = typeof value === "string" ? value : null;
          }}
          onValueChange={(val, eventDetails) => {
            if (typeof val !== "string") return;
            if (eventDetails.reason === "input-change") {
              setQuery(val);
              trackCaret();
              return;
            }
            if (val === "") setQuery("");
          }}
          filter={paletteFilter}
        >
          <div ref={inputWrapRef} className="relative">
            <PaletteQueryMirror
              query={query}
              wrapRef={inputWrapRef}
              visible={spacesLayout}
            />
            <AutocompleteInput
              placeholder={
                spacesLayout
                  ? "Search commands and tasks, or filter with created-by:"
                  : bluebirdEnabled
                    ? "Search commands, channels, and tasks…"
                    : "Search commands and tasks…"
              }
              autoFocus
              showClear
              className={
                spacesLayout
                  ? cn(
                      "[&_input]:whitespace-pre [&_input]:font-mono [&_input]:text-[13px] [&_input]:tracking-normal",
                      "[&_input]:text-transparent [&_input]:caret-(--gray-12) [&_input]:placeholder:text-(--gray-9)",
                      "[&_input]:selection:bg-(--blue-a4) [&_input]:selection:text-transparent",
                    )
                  : undefined
              }
              onKeyDown={onInputKeyDown}
              onKeyUp={trackCaret}
              onClick={trackCaret}
              onSelect={trackCaret}
            />
          </div>
          {keyChips.length > 0 && (
            <PaletteFilterChips
              key={mode}
              chips={keyChips}
              collapsedCount={COLLAPSED_CHIP_COUNT}
            />
          )}
          {showMatchSummary ? (
            <div className="border-(--gray-a4) border-b px-3 py-1.5 text-(--gray-9) text-xs tabular-nums">
              {partialResults
                ? "Some matching tasks may not be shown."
                : matchSummary(matchCount, shownCount, hasRepairs)}
            </div>
          ) : (
            query !== "" && (
              <AutocompleteStatus
                emptyContent={
                  <span>
                    No results for <strong>"{query}"</strong>
                  </span>
                }
              />
            )
          )}
          <AutocompleteList className="max-h-[60vh]">
            {(section: CommandSection) => (
              <AutocompleteGroup key={section.label} items={section.items}>
                <AutocompleteLabel>{section.label}</AutocompleteLabel>
                <AutocompleteCollection>
                  {(cmd: Command) => (
                    <AutocompleteItem
                      key={cmd.id}
                      value={cmd.id}
                      onClick={() => handleSelect(cmd.id)}
                      className="group flex h-auto! min-h-7 w-full items-center gap-2 py-1.5 pr-2 text-left [&>span]:w-full [&>span]:overflow-visible"
                    >
                      {cmd.icon}
                      <span className="wrap-break-word min-w-0 whitespace-normal">
                        {cmd.label}
                        {cmd.subtitle && (
                          <span className="block truncate text-gray-9 text-xs">
                            {cmd.subtitle}
                          </span>
                        )}
                      </span>
                      {cmd.detail && (
                        <span className="shrink-0 text-gray-9">
                          · {cmd.detailPrefix ?? "#"}
                          {cmd.detail}
                        </span>
                      )}
                      {cmd.shortcut && (
                        <span className="ml-auto flex shrink-0 items-center gap-2 pl-2">
                          {formatHotkeyParts(cmd.shortcut).map((part) => (
                            <Kbd key={part}>{part}</Kbd>
                          ))}
                        </span>
                      )}
                    </AutocompleteItem>
                  )}
                </AutocompleteCollection>
              </AutocompleteGroup>
            )}
          </AutocompleteList>
        </Autocomplete>
        <CommandKeyHints>
          {hasFilterTokens && (
            <div className="flex items-center gap-2">
              <KbdGroup>
                <Kbd>{formatHotkeyParts("mod+s").join("")}</Kbd>
              </KbdGroup>
              <span className="text-xs">
                save search
                {matchCount === 0 && " · no matches yet"}
              </span>
            </div>
          )}
        </CommandKeyHints>
      </DialogContent>
    </Dialog>
  );
}

function useRecentCommandSections(
  baseSections: CommandSection[],
  query: string,
  recentCommands: Command[],
): CommandSection[] {
  return useMemo(() => {
    if (query.trim() || recentCommands.length === 0) return baseSections;
    const currentCommands = new Map(
      baseSections.flatMap((section) =>
        section.items.map((command) => [command.id, command] as const),
      ),
    );
    const recentItems = recentCommands.map(
      (command) => currentCommands.get(command.id) ?? command,
    );
    const recentIds = new Set(recentItems.map((command) => command.id));
    return [
      { label: "Recent", items: recentItems },
      ...baseSections.flatMap((section) => {
        const items = section.items.filter(
          (command) => !recentIds.has(command.id),
        );
        return items.length > 0 ? [{ ...section, items }] : [];
      }),
    ];
  }, [baseSections, query, recentCommands]);
}

export function CommandMenu({ open, onOpenChange }: CommandMenuProps) {
  const spacesLayout = useChannelsLayout();
  const openSettingsDialog = openSettings;
  const closeSettingsDialog = closeSettings;
  const { folders } = useFolders();
  const bluebirdEnabled = useFeatureFlag(
    PROJECT_BLUEBIRD_FLAG,
    import.meta.env.DEV,
  );
  const loopsEnabled = useFeatureFlag(LOOPS_FLAG);
  const inboxAvailable = useInboxAvailable();
  const spendAnalysisEnabled = useSpendAnalysisEnabled();
  const { channels } = useChannels({ enabled: bluebirdEnabled });
  const { theme, setTheme } = useThemeStore();
  const toggleLeftSidebar = useSidebarStore((state) => state.toggle);
  const openFeedback = useFeedbackStore((state) => state.open);
  const view = useAppView();
  const { data: tasks = [] } = useTasks();
  const archivedTaskIds = useArchivedTaskIds();
  const { data: workspaces, isFetched: workspacesFetched } = useWorkspaces();
  const provisioningTaskIds = useProvisioningStore(
    (state) => state.activeTasks,
  );
  const [query, setQuery] = useState("");
  const [createChannelOpen, setCreateChannelOpen] = useState(false);
  const [createChannelUsed, setCreateChannelUsed] = useState(false);
  const [recentCommands, setRecentCommands] = useState<Command[]>([]);
  const { remoteQuery, remoteSearchAllowedRef, searchResults } =
    useRemoteTaskSearch(open, query);
  const { repoPath } = useFileSearchContext();
  const canSearchFiles = !!repoPath;
  const openFilePicker = useFileSearchStore((state) => state.openPicker);
  const systemPrefersDark = useSystemPrefersDark();

  // The review panel lives in the task-detail view, so the command only makes
  // sense when a task is open. Elsewhere (e.g. the new-task screen) it would be
  // a no-op, so we omit it below rather than show a dead entry.
  const reviewTaskId = view.type === "task-detail" ? view.taskId : undefined;
  const openReviewPanel = useOpenReviewPanel(reviewTaskId);

  // Archiving acts on the open task, so the command needs the task itself and
  // drops out of the list when the palette can't find it.
  const openedTask = tasks.find((task) => task.id === reviewTaskId);
  const { requestArchive, dialog: archiveDialog } = useTaskArchive(openedTask, {
    navigateUnscoped: !openedTask?.channel,
  });

  useEffect(() => {
    if (open) track(ANALYTICS_EVENTS.COMMAND_MENU_OPENED);
  }, [open]);

  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      if (!nextOpen) setQuery("");
      onOpenChange(nextOpen);
    },
    [onOpenChange],
  );

  const handleCreateChannel = useCallback(() => {
    setCreateChannelUsed(true);
    setCreateChannelOpen(true);
  }, []);

  const { channelSections, commandSections, taskSections } =
    useCommandMenuSections({
      archivedTaskIds,
      bluebirdEnabled,
      canArchiveTask: !!openedTask,
      canSearchFiles,
      channels,
      closeSettingsDialog,
      folders,
      inboxAvailable,
      loopsEnabled,
      onCreateChannel: handleCreateChannel,
      openFeedback,
      openFilePicker,
      openReviewPanel,
      openSettingsDialog,
      provisioningTaskIds,
      requestArchive,
      reviewTaskId,
      setTheme,
      spacesLayout,
      spendAnalysisEnabled,
      systemPrefersDark,
      tasks,
      theme,
      toggleLeftSidebar,
      workspaces,
      workspacesFetched,
    });

  const searchSections = useSearchSections({
    remoteQuery,
    searchResults,
    tasks,
    taskSections,
    channels,
    bluebirdEnabled,
    spacesLayout,
  });

  const [feedModalQuery, setFeedModalQuery] = useState<string | null>(null);
  const onSaveAsFeed = useCallback(
    (feedQuery: string) => {
      handleOpenChange(false);
      setFeedModalQuery(feedQuery);
    },
    [handleOpenChange],
  );

  const [caret, setCaret] = useState(0);
  const inputWrapRef = useRef<HTMLDivElement>(null);
  const trackCaret = useCallback(() => {
    const position =
      inputWrapRef.current?.querySelector("input")?.selectionStart;
    if (position != null) setCaret(position);
  }, []);
  // Restore the caret after React applies a completed suggestion.
  const pendingCaret = useRef<number | null>(null);
  useLayoutEffect(() => {
    if (pendingCaret.current == null) return;
    const input = inputWrapRef.current?.querySelector("input");
    input?.setSelectionRange(pendingCaret.current, pendingCaret.current);
    input?.focus();
    pendingCaret.current = null;
  });
  const onApplyFilter = useCallback((next: string, nextCaret: number) => {
    setQuery(next);
    setCaret(nextCaret);
    pendingCaret.current = nextCaret;
  }, []);

  const [showAllFor, setShowAllFor] = useState<string | null>(null);
  const resultLimit =
    showAllFor === query ? Number.MAX_SAFE_INTEGER : DEFAULT_RESULT_LIMIT;
  const showAllMatches = useCallback(() => setShowAllFor(query), [query]);

  const feedQuery = useFeedQueryCommands({
    query,
    caret,
    enabled: open && spacesLayout,
    limit: resultLimit,
    onApply: onApplyFilter,
    onShowAll: showAllMatches,
  });
  const { mode, scope, hasFilterTokens, searchText, keyChips, matchCount } =
    feedQuery;

  // Keep the debounce's gate in step with the condition that decides whether
  // the remote search is even rendered, so the two can't drift.
  useEffect(() => {
    const browsing = mode === "browsing" || mode === "completingKey";
    remoteSearchAllowedRef.current = browsing && !scope;
  }, [mode, scope, remoteSearchAllowedRef]);

  const baseSections = useMemo(() => {
    const browsing = mode === "browsing" || mode === "completingKey";
    const showCommands = browsing && (!scope || scope === "command");
    const showChannels = browsing && (!scope || scope === "space");
    const showPlainTasks = browsing && !scope;
    const showRemoteSearch = browsing && !scope;
    return prioritizeExactCommandMatches(
      [
        ...feedQuery.sections,
        ...(showRemoteSearch ? searchSections : []),
        ...(showCommands ? commandSections : []),
        ...(showChannels ? channelSections : []),
        ...(showPlainTasks ? taskSections : []),
      ],
      searchText,
    );
  }, [
    feedQuery.sections,
    searchSections,
    commandSections,
    channelSections,
    taskSections,
    mode,
    scope,
    searchText,
  ]);

  const sections = useRecentCommandSections(
    baseSections,
    query,
    recentCommands,
  );

  const paletteFilter = useCallback(
    (command: { label: string; keywords?: string }) =>
      matchesCommandSearch(command, searchText),
    [searchText],
  );

  const allCommands = useMemo(
    () => sections.flatMap((s) => s.items),
    [sections],
  );

  const highlightedId = useRef<string | null>(null);
  const showMatchSummary = mode === "querying" || matchCount != null;

  const handleSelect = (id: string | null): void => {
    if (id === null) return;
    const cmd = allCommands.find((c) => c.id === id);
    if (!cmd) return;
    track(ANALYTICS_EVENTS.COMMAND_MENU_ACTION, {
      action_type: cmd.action,
      channel_id: cmd.channelId,
    });
    if (!cmd.keepOpen) {
      setRecentCommands((recent) => addRecentCommand(recent, cmd));
    }
    cmd.onRun();
    if (cmd.keepOpen) return;
    handleOpenChange(false);
  };

  const onInputKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (
      event.key.toLowerCase() === "s" &&
      (event.metaKey || event.ctrlKey) &&
      hasFilterTokens
    ) {
      event.preventDefault();
      track(ANALYTICS_EVENTS.COMMAND_MENU_ACTION, { action_type: "save-feed" });
      onSaveAsFeed(query.trim());
      return;
    }
    if (event.key !== "Tab") return;
    if (mode === "completingKey" && keyChips.length > 0) {
      event.preventDefault();
      keyChips[0].apply();
      return;
    }
    const highlighted = allCommands.find(
      (c) => c.id === highlightedId.current && c.keepOpen,
    );
    const target = highlighted ?? allCommands.find((c) => c.keepOpen);
    if (!target) return;
    event.preventDefault();
    target.onRun();
  };

  return (
    <>
      <CommandMenuDialog
        bluebirdEnabled={bluebirdEnabled}
        feedQuery={feedQuery}
        handleSelect={handleSelect}
        highlightedId={highlightedId}
        inputWrapRef={inputWrapRef}
        onInputKeyDown={onInputKeyDown}
        onOpenChange={handleOpenChange}
        open={open}
        paletteFilter={paletteFilter}
        query={query}
        sections={sections}
        setQuery={setQuery}
        showMatchSummary={showMatchSummary}
        spacesLayout={spacesLayout}
        trackCaret={trackCaret}
      />
      <TaskFeedModal
        open={feedModalQuery !== null}
        onOpenChange={(modalOpen) => {
          if (!modalOpen) setFeedModalQuery(null);
        }}
        initialQuery={feedModalQuery ?? undefined}
        surface="command_menu"
        onCreated={(feed) => navigateToFeed(feed.id)}
      />
      {createChannelUsed && (
        <Suspense fallback={null}>
          <CreateChannelModalLazy
            open={createChannelOpen}
            onOpenChange={setCreateChannelOpen}
            surface="command_menu"
          />
        </Suspense>
      )}
      {/* Outlives the palette, which closes as the command runs. */}
      {archiveDialog}
    </>
  );
}
