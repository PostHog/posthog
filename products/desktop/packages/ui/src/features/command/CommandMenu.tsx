import {
  ArchiveIcon,
  CaretLeftIcon,
  CaretRightIcon,
  ChartLine,
  EnvelopeSimple,
  Gauge,
  GitDiffIcon,
  SquaresFourIcon,
} from "@phosphor-icons/react";
import { workspaceIdSet } from "@posthog/core/command-center/eligibility";
import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
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
import {
  ANALYTICS_EVENTS,
  type CommandMenuAction,
} from "@posthog/shared/analytics-events";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { useTaskArchive } from "@posthog/ui/features/archive/useTaskArchive";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import {
  EDITOR_TEXT_CLASS,
  FeedQueryHighlight,
} from "@posthog/ui/features/canvas/components/FeedQueryInput";
import { TaskFeedModal } from "@posthog/ui/features/canvas/components/TaskFeedModal";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { getDefaultReviewMode } from "@posthog/ui/features/code-review/getDefaultReviewMode";
import { useReviewNavigationStore } from "@posthog/ui/features/code-review/reviewNavigationStore";
import { CommandKeyHints } from "@posthog/ui/features/command/CommandKeyHints";
import {
  addRecentCommand,
  matchesCommandSearch,
  prioritizeExactCommandMatches,
} from "@posthog/ui/features/command/commandSearch";
import { useFileSearchStore } from "@posthog/ui/features/command/fileSearchStore";
import {
  formatHotkeyParts,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";
import { PaletteFilterChips } from "@posthog/ui/features/command/PaletteFilterChips";
import { TaskCommandIcon } from "@posthog/ui/features/command/TaskCommandIcon";
import { taskSearchDelay } from "@posthog/ui/features/command/taskSearchQuery";
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
import { useTaskSearch } from "@posthog/ui/features/command/useTaskSearch";
import { useChannelReportsEnabled } from "@posthog/ui/features/feature-flags/useChannelReportsEnabled";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
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
import { LoopIcon } from "@posthog/ui/primitives/LoopIcon";
import {
  goBackInHistory,
  goForwardInHistory,
  navigateToArchived,
  navigateToChannel,
  navigateToCommandCenter,
  navigateToFeed,
  navigateToInbox,
  navigateToLoops,
} from "@posthog/ui/router/navigationBridge";
import { useAppView } from "@posthog/ui/router/useAppView";
import { openTask, openTaskInput } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { showLogFolder } from "@posthog/ui/shell/openExternal";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import {
  DesktopIcon,
  FileTextIcon,
  GearIcon,
  HomeIcon,
  MagnifyingGlassIcon,
  MoonIcon,
  ReloadIcon,
  SunIcon,
  ViewVerticalIcon,
  ZoomInIcon,
  ZoomOutIcon,
} from "@radix-ui/react-icons";
import {
  type KeyboardEvent as ReactKeyboardEvent,
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
  // With channel reports on, spaces own reports and the inbox entry goes away.
  const channelReportsEnabled = useChannelReportsEnabled();
  const spendAnalysisEnabled = useSpendAnalysisEnabled();
  const { channels } = useChannels({ enabled: bluebirdEnabled });
  const { theme, setTheme } = useThemeStore();
  const toggleLeftSidebar = useSidebarStore((state) => state.toggle);
  const view = useAppView();
  const setReviewMode = useReviewNavigationStore(
    (state) => state.setReviewMode,
  );
  const getReviewMode = useReviewNavigationStore(
    (state) => state.getReviewMode,
  );
  const { data: tasks = [] } = useTasks();
  const archivedTaskIds = useArchivedTaskIds();
  const { data: workspaces, isFetched: workspacesFetched } = useWorkspaces();
  const provisioningTaskIds = useProvisioningStore(
    (state) => state.activeTasks,
  );
  const [query, setQuery] = useState("");
  const [recentCommands, setRecentCommands] = useState<Command[]>([]);
  const [remoteQuery, setRemoteQuery] = useState("");
  // The legacy title search only ever surfaces while the palette is browsing
  // (see `showRemoteSearch` below). The feed-query `mode` that decides that is
  // derived further down, after this debounce, so the effect reads the latest
  // value through a ref instead because a filter query must not start a search whose
  // results the palette then throws away.
  const remoteSearchAllowedRef = useRef(true);
  const { repoPath } = useFileSearchContext();
  const canSearchFiles = !!repoPath;
  const openFilePicker = useFileSearchStore((state) => state.openPicker);
  const [systemPrefersDark, setSystemPrefersDark] = useState(
    () => window.matchMedia("(prefers-color-scheme: dark)").matches,
  );

  useEffect(() => {
    const trimmed = query.trim();
    const delay = taskSearchDelay(trimmed);
    if (!open || delay === null) {
      setRemoteQuery("");
      return;
    }
    const timer = window.setTimeout(
      () => setRemoteQuery(remoteSearchAllowedRef.current ? trimmed : ""),
      delay,
    );
    return () => window.clearTimeout(timer);
  }, [open, query]);

  const { data: searchResults = [] } = useTaskSearch(remoteQuery, open);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (e: MediaQueryListEvent) =>
      setSystemPrefersDark(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  // The review panel lives in the task-detail view, so the command only makes
  // sense when a task is open. Elsewhere (e.g. the new-task screen) it would be
  // a no-op, so we omit it below rather than show a dead entry.
  const reviewTaskId = view.type === "task-detail" ? view.taskId : undefined;

  const openReviewPanel = useCallback(() => {
    if (!reviewTaskId) return;
    const mode = getReviewMode(reviewTaskId);
    if (mode === "closed") {
      setReviewMode(reviewTaskId, getDefaultReviewMode());
    }
  }, [reviewTaskId, getReviewMode, setReviewMode]);

  // Archiving acts on the open task, so the command needs the task itself and
  // drops out of the list when the palette can't find it.
  const openedTask = tasks.find((task) => task.id === reviewTaskId);
  const { requestArchive, dialog: archiveDialog } = useTaskArchive(openedTask, {
    navigateUnscoped: !openedTask?.channel,
  });

  useEffect(() => {
    if (open) {
      track(ANALYTICS_EVENTS.COMMAND_MENU_OPENED);
    } else {
      setQuery("");
    }
  }, [open]);

  const themeOptions = useMemo<Command[]>(() => {
    const options: Command[] = [];
    if (theme !== "light") {
      options.push({
        id: "switch-theme-light",
        label: "Switch to light mode",
        keywords: "theme appearance",
        icon: <SunIcon className="h-3 w-3 text-gray-11" />,
        action: "toggle-theme",
        onRun: () => setTheme("light"),
      });
    }
    if (theme !== "dark") {
      options.push({
        id: "switch-theme-dark",
        label: "Switch to dark mode",
        keywords: "theme appearance",
        icon: <MoonIcon className="h-3 w-3 text-gray-11" />,
        action: "toggle-theme",
        onRun: () => setTheme("dark"),
      });
    }
    const systemMatchesCurrent =
      (theme === "dark" && systemPrefersDark) ||
      (theme === "light" && !systemPrefersDark);
    if (theme !== "system" && !systemMatchesCurrent) {
      options.push({
        id: "switch-theme-system",
        label: "Switch to system theme",
        keywords: "theme appearance auto",
        icon: <DesktopIcon className="h-3 w-3 text-gray-11" />,
        action: "toggle-theme",
        onRun: () => setTheme("system"),
      });
    }
    return options;
  }, [theme, setTheme, systemPrefersDark]);

  const commandSections = useMemo<CommandSection[]>(() => {
    const navigation: Command[] = [
      {
        id: "home",
        label: "Home",
        icon: <HomeIcon className="h-3 w-3 text-gray-11" />,
        action: "home",
        onRun: () => {
          closeSettingsDialog();
          openTaskInput();
        },
      },
      {
        id: "settings",
        label: "Settings",
        icon: <GearIcon className="h-3 w-3 text-gray-11" />,
        action: "settings",
        shortcut: SHORTCUTS.SETTINGS,
        onRun: () => openSettingsDialog(),
      },
      ...(channelReportsEnabled
        ? []
        : [
            {
              id: "inbox",
              label: "Self-driving",
              keywords: "reports pull requests agents notifications",
              icon: <EnvelopeSimple size={12} className="text-gray-11" />,
              action: "open-inbox",
              shortcut: SHORTCUTS.INBOX,
              onRun: () => {
                closeSettingsDialog();
                navigateToInbox();
              },
            } satisfies Command,
          ]),
      {
        id: "archived",
        label: "Archived",
        keywords: "archive archived tasks",
        icon: <ArchiveIcon size={12} className="text-gray-11" />,
        action: "open-archived",
        onRun: () => {
          closeSettingsDialog();
          navigateToArchived();
        },
      },
      {
        id: "command-center",
        label: "Command center",
        keywords: "grid tasks parallel dashboard",
        icon: <SquaresFourIcon className="h-3 w-3 text-gray-11" />,
        action: "open-command-center",
        onRun: () => {
          closeSettingsDialog();
          navigateToCommandCenter();
        },
      },
      ...(loopsEnabled
        ? [
            {
              id: "loops",
              label: "Loops",
              keywords: "automations schedules recurring",
              icon: <LoopIcon size={12} className="text-gray-11" />,
              action: "open-loops" as CommandMenuAction,
              onRun: () => {
                closeSettingsDialog();
                navigateToLoops();
              },
            },
          ]
        : []),
      // Gated like every other cost-management entry point: without spend
      // analysis the settings page is hidden and redirects to General, so the
      // command would not do what its label says.
      ...(spendAnalysisEnabled
        ? [
            {
              id: "cost-management",
              label: "Cost management",
              keywords: "cost spend limits budget savings recommendations",
              icon: <Gauge size={12} className="text-gray-11" />,
              action: "open-cost-management" as CommandMenuAction,
              onRun: () => openSettingsDialog("cost-management"),
            },
          ]
        : []),
      {
        id: "plan-usage",
        label: "Plan & usage",
        keywords: "billing spend cost credits usage plan",
        icon: <ChartLine size={12} className="text-gray-11" />,
        action: "open-usage",
        onRun: () => openSettingsDialog("plan-usage"),
      },
      {
        id: "go-back",
        label: "Go back",
        keywords: "navigate history previous",
        icon: <CaretLeftIcon size={12} className="text-gray-11" />,
        action: "go-back",
        shortcut: SHORTCUTS.GO_BACK,
        onRun: goBackInHistory,
      },
      {
        id: "go-forward",
        label: "Go forward",
        keywords: "navigate history next",
        icon: <CaretRightIcon size={12} className="text-gray-11" />,
        action: "go-forward",
        shortcut: SHORTCUTS.GO_FORWARD,
        onRun: goForwardInHistory,
      },
    ];

    const actions: Command[] = [
      {
        id: "new-task",
        label: "New task",
        keywords: "create",
        icon: <FileTextIcon className="h-3 w-3 text-gray-11" />,
        action: "new-task",
        shortcut: SHORTCUTS.NEW_TASK,
        onRun: () => {
          closeSettingsDialog();
          openTaskInput();
        },
      },
      {
        id: "toggle-left-sidebar",
        label: "Toggle left sidebar",
        icon: <ViewVerticalIcon className="h-3 w-3 text-gray-11" />,
        action: "toggle-left-sidebar",
        shortcut: SHORTCUTS.TOGGLE_LEFT_SIDEBAR,
        onRun: toggleLeftSidebar,
      },
      ...(reviewTaskId
        ? [
            {
              id: "open-review-panel",
              label: "Open diff view",
              icon: <GitDiffIcon className="h-3 w-3 text-gray-11" />,
              action: "open-review-panel" as CommandMenuAction,
              shortcut: SHORTCUTS.TOGGLE_REVIEW_PANEL,
              onRun: openReviewPanel,
            },
          ]
        : []),
      ...(openedTask
        ? [
            {
              id: "archive-task",
              label: "Archive task",
              keywords: "archive close remove",
              icon: <ArchiveIcon size={12} className="text-gray-11" />,
              action: "archive-task" as CommandMenuAction,
              shortcut: SHORTCUTS.ARCHIVE_TASK,
              onRun: requestArchive,
            },
          ]
        : []),
      // Last, because the first row is what a stray Enter runs.
      ...themeOptions,
    ];

    if (canSearchFiles) {
      actions.push({
        id: "search-files",
        label: "Search files",
        keywords: "file find open",
        icon: <MagnifyingGlassIcon className="h-3 w-3 text-gray-11" />,
        action: "search-files",
        onRun: openFilePicker,
      });
    }

    const developer: Command[] = [
      {
        id: "show-log-folder",
        label: "Show log folder",
        keywords: "logs debug files finder",
        icon: <FileTextIcon className="h-3 w-3 text-gray-11" />,
        action: "show-log-folder",
        onRun: showLogFolder,
      },
      {
        id: "reload-window",
        label: "Reload window",
        keywords: "refresh restart",
        icon: <ReloadIcon className="h-3 w-3 text-gray-11" />,
        action: "reload-window",
        shortcut: SHORTCUTS.RELOAD_WINDOW,
        onRun: () => window.location.reload(),
      },
    ];

    const viewCommands: Command[] = [
      {
        id: "zoom-in",
        label: "Zoom in",
        keywords: "zoom increase larger",
        icon: <ZoomInIcon className="h-3 w-3 text-gray-11" />,
        action: "zoom-in",
        shortcut: SHORTCUTS.ZOOM_IN,
        onRun: () =>
          void resolveService<HostTrpcClient>(
            HOST_TRPC_CLIENT,
          ).os.zoomIn.mutate(),
      },
      {
        id: "zoom-out",
        label: "Zoom out",
        keywords: "zoom decrease smaller",
        icon: <ZoomOutIcon className="h-3 w-3 text-gray-11" />,
        action: "zoom-out",
        shortcut: SHORTCUTS.ZOOM_OUT,
        onRun: () =>
          void resolveService<HostTrpcClient>(
            HOST_TRPC_CLIENT,
          ).os.zoomOut.mutate(),
      },
      {
        id: "zoom-reset",
        label: "Reset zoom",
        keywords: "zoom actual size default",
        icon: <MagnifyingGlassIcon className="h-3 w-3 text-gray-11" />,
        action: "zoom-reset",
        shortcut: SHORTCUTS.RESET_ZOOM,
        onRun: () =>
          void resolveService<HostTrpcClient>(
            HOST_TRPC_CLIENT,
          ).os.resetZoom.mutate(),
      },
    ];

    const out: CommandSection[] = [
      { label: "Actions", items: actions },
      { label: "Navigation", items: navigation },
      { label: "View", items: viewCommands },
      { label: "Developer", items: developer },
    ];

    if (folders.length > 0) {
      out.push({
        label: "New task in folder",
        items: folders.map((folder) => ({
          id: `new-task-folder-${folder.id}`,
          label: `New task in ${folder.name}`,
          keywords: folder.path,
          icon: <FileTextIcon className="h-3 w-3 text-gray-11" />,
          action: "new-task",
          onRun: () => {
            closeSettingsDialog();
            openTaskInput(folder.id);
          },
        })),
      });
    }

    return out;
  }, [
    folders,
    themeOptions,
    openSettingsDialog,
    closeSettingsDialog,
    toggleLeftSidebar,
    openReviewPanel,
    reviewTaskId,
    openedTask,
    requestArchive,
    canSearchFiles,
    openFilePicker,
    loopsEnabled,
    channelReportsEnabled,
    spendAnalysisEnabled,
  ]);

  const taskSections = useMemo<CommandSection[]>(() => {
    const workspaceIds = workspaceIdSet(workspaces);
    const visibleTasks = tasks.filter(
      (task) =>
        !archivedTaskIds.has(task.id) &&
        (!workspacesFetched ||
          workspaceIds.has(task.id) ||
          provisioningTaskIds.has(task.id)),
    );
    if (visibleTasks.length === 0) return [];
    const channelsById = new Map(
      channels.map((channel) => [channel.id, channel] as const),
    );
    return [
      {
        label: "Tasks",
        items: visibleTasks.map((task) => {
          const channel = task.channel
            ? channelsById.get(task.channel)
            : undefined;
          return {
            id: `task-${task.id}`,
            label: task.title,
            detail: channel?.name,
            // Include the channel name so searching it surfaces filed tasks.
            keywords: channel?.name,
            icon: <TaskCommandIcon task={task} />,
            action: "open-task" as CommandMenuAction,
            channelId: bluebirdEnabled ? channel?.id : undefined,
            onRun: () => {
              closeSettingsDialog();
              // Bluebird: a task filed to a channel opens in the channel-
              // organized view under /website, keeping the channels chrome.
              // Otherwise fall back to the /code task detail.
              const channelTarget =
                bluebirdEnabled && channel
                  ? { channelId: channel.id }
                  : undefined;
              void openTask(task, channelTarget);
            },
          };
        }),
      },
    ];
  }, [
    tasks,
    archivedTaskIds,
    workspaces,
    workspacesFetched,
    provisioningTaskIds,
    channels,
    bluebirdEnabled,
    closeSettingsDialog,
  ]);

  const channelSections = useMemo<CommandSection[]>(() => {
    if (channels.length === 0) return [];
    return [
      {
        label: spacesLayout ? "Spaces" : "Channels",
        items: channels.map((channel) => ({
          id: `channel-${channel.id}`,
          label: channel.name,
          keywords: "space channel",
          icon: channelGlyph(channel.name, {
            personal: channel.channelType === "personal",
            size: 12,
            space: spacesLayout,
            className: "text-muted-foreground",
          }),
          action: "open-channel" as CommandMenuAction,
          channelId: channel.id,
          onRun: () => {
            closeSettingsDialog();
            navigateToChannel(channel.id);
          },
        })),
      },
    ];
  }, [channels, closeSettingsDialog, spacesLayout]);

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
      onOpenChange(false);
      setFeedModalQuery(feedQuery);
    },
    [onOpenChange],
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
  const {
    mode,
    scope,
    hasFilterTokens,
    searchText,
    keyChips,
    matchCount,
    partialResults,
    shownCount,
    hasRepairs,
  } = feedQuery;

  // Keep the debounce's gate in step with the condition that decides whether
  // the remote search is even rendered, so the two can't drift.
  useEffect(() => {
    const browsing = mode === "browsing" || mode === "completingKey";
    remoteSearchAllowedRef.current = browsing && !scope;
  }, [mode, scope]);

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

  const sections = useMemo(() => {
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
      ...baseSections
        .map((section) => ({
          ...section,
          items: section.items.filter((command) => !recentIds.has(command.id)),
        }))
        .filter((section) => section.items.length > 0),
    ];
  }, [baseSections, query, recentCommands]);

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
    onOpenChange(false);
    setQuery("");
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
      <TaskFeedModal
        open={feedModalQuery !== null}
        onOpenChange={(modalOpen) => {
          if (!modalOpen) setFeedModalQuery(null);
        }}
        initialQuery={feedModalQuery ?? undefined}
        surface="command_menu"
        onCreated={(feed) => navigateToFeed(feed.id)}
      />
      {/* Outlives the palette, which closes as the command runs. */}
      {archiveDialog}
    </>
  );
}
