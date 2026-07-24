import {
  CaretLeftIcon,
  CaretRightIcon,
  ChartLine,
  EnvelopeSimple,
  HashIcon,
  RepeatIcon,
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
  Dialog,
  DialogContent,
  Kbd,
} from "@posthog/quill";
import { LOOPS_FLAG, PROJECT_BLUEBIRD_FLAG } from "@posthog/shared";
import {
  ANALYTICS_EVENTS,
  type CommandMenuAction,
} from "@posthog/shared/analytics-events";
import type { Task } from "@posthog/shared/domain-types";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useTaskChannelMap } from "@posthog/ui/features/canvas/hooks/useTaskChannelMap";
import { useReviewNavigationStore } from "@posthog/ui/features/code-review/reviewNavigationStore";
import { CommandKeyHints } from "@posthog/ui/features/command/CommandKeyHints";
import { useFileSearchStore } from "@posthog/ui/features/command/fileSearchStore";
import {
  formatHotkeyParts,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";
import { useFileSearchContext } from "@posthog/ui/features/command/useFileSearchContext";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useFolders } from "@posthog/ui/features/folders/useFolders";
import { useProvisioningStore } from "@posthog/ui/features/provisioning/store";
import {
  closeSettings,
  openSettings,
} from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { TaskIcon } from "@posthog/ui/features/sidebar/components/items/TaskIcon";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { useTaskPrStatus } from "@posthog/ui/features/sidebar/useTaskPrStatus";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useWorkspaces } from "@posthog/ui/features/workspace/useWorkspace";
import {
  goBackInHistory,
  goForwardInHistory,
  navigateToChannel,
  navigateToCommandCenter,
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
  LightningBoltIcon,
  MagnifyingGlassIcon,
  MoonIcon,
  ReloadIcon,
  SunIcon,
  ViewVerticalIcon,
  ZoomInIcon,
  ZoomOutIcon,
} from "@radix-ui/react-icons";
import { useCallback, useEffect, useMemo, useState } from "react";

interface CommandMenuProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type Command = {
  id: string;
  label: string;
  /** Muted trailing detail shown after a middot, e.g. a task's channel. */
  detail?: string;
  keywords?: string;
  icon: React.ReactNode;
  action: CommandMenuAction;
  /** Channel in scope for the bluebird open-channel / open-task actions. */
  channelId?: string;
  /** Hotkey string (e.g. "mod+b") shown right-aligned when present. */
  shortcut?: string;
  onRun: () => void;
};

type CommandSection = { label: string; items: Command[] };

/**
 * Task icon for the command palette. Renders the same shared `TaskIcon` as
 * the sidebar — cloud run status, PR/branch status, etc. — deriving its
 * inputs from the raw task and a per-task PR-status query.
 */
function TaskCommandIcon({ task }: { task: Task }) {
  const { prState, hasDiff } = useTaskPrStatus({
    id: task.id,
    cloudPrUrl: null,
    taskRunEnvironment: task.latest_run?.environment,
  });
  const stateSlackThreadUrl = (
    task.latest_run?.state as { slack_thread_url?: unknown } | undefined
  )?.slack_thread_url;
  const slackThreadUrl =
    typeof stateSlackThreadUrl === "string" ? stateSlackThreadUrl : undefined;
  return (
    <TaskIcon
      workspaceMode={task.latest_run?.environment}
      taskRunStatus={task.latest_run?.status}
      originProduct={task.origin_product}
      slackThreadUrl={slackThreadUrl}
      prState={prState}
      hasDiff={hasDiff}
    />
  );
}

export function CommandMenu({ open, onOpenChange }: CommandMenuProps) {
  const openSettingsDialog = openSettings;
  const closeSettingsDialog = closeSettings;
  const { folders } = useFolders();
  // Channels (and the task→channel detail) are a Project Bluebird feature. Gate
  // the channel fetches behind the flag so they never reach ungated users.
  const bluebirdEnabled = useFeatureFlag(
    PROJECT_BLUEBIRD_FLAG,
    import.meta.env.DEV,
  );
  const loopsEnabled = useFeatureFlag(LOOPS_FLAG, import.meta.env.DEV);
  const { channels } = useChannels({ enabled: bluebirdEnabled });
  const taskChannelMap = useTaskChannelMap(channels, {
    enabled: open && bluebirdEnabled,
  });
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
  const { repoPath } = useFileSearchContext();
  const canSearchFiles = !!repoPath;
  const openFilePicker = useFileSearchStore((state) => state.openPicker);
  const [systemPrefersDark, setSystemPrefersDark] = useState(
    () => window.matchMedia("(prefers-color-scheme: dark)").matches,
  );

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
      setReviewMode(reviewTaskId, "split");
    }
  }, [reviewTaskId, getReviewMode, setReviewMode]);

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
      {
        id: "inbox",
        label: "Inbox",
        keywords: "reports pull requests agents notifications",
        icon: <EnvelopeSimple size={12} className="text-gray-11" />,
        action: "open-inbox",
        shortcut: SHORTCUTS.INBOX,
        onRun: () => {
          closeSettingsDialog();
          navigateToInbox();
        },
      },
      {
        id: "command-center",
        label: "Command center",
        keywords: "lightning grid tasks parallel dashboard",
        icon: <LightningBoltIcon className="h-3 w-3 text-gray-11" />,
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
              icon: <RepeatIcon size={12} className="text-gray-11" />,
              action: "open-loops" as CommandMenuAction,
              onRun: () => {
                closeSettingsDialog();
                navigateToLoops();
              },
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
      ...themeOptions,
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
              label: "Open review panel",
              icon: (
                <ViewVerticalIcon className="h-3 w-3 rotate-180 text-gray-11" />
              ),
              action: "open-review-panel" as CommandMenuAction,
              shortcut: SHORTCUTS.TOGGLE_REVIEW_PANEL,
              onRun: openReviewPanel,
            },
          ]
        : []),
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
    canSearchFiles,
    openFilePicker,
    loopsEnabled,
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
    return [
      {
        label: "Tasks",
        items: visibleTasks.map((task) => {
          const channel = taskChannelMap.get(task.id);
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
    taskChannelMap,
    bluebirdEnabled,
    closeSettingsDialog,
  ]);

  const channelSections = useMemo<CommandSection[]>(() => {
    if (channels.length === 0) return [];
    return [
      {
        label: "Channels",
        items: channels.map((channel) => ({
          id: `channel-${channel.id}`,
          label: channel.name,
          keywords: "channel",
          icon: <HashIcon size={12} className="text-gray-11" />,
          action: "open-channel" as CommandMenuAction,
          channelId: channel.id,
          onRun: () => {
            closeSettingsDialog();
            navigateToChannel(channel.id);
          },
        })),
      },
    ];
  }, [channels, closeSettingsDialog]);

  // Commands, channels, and tasks share a single filterable list.
  const sections = useMemo(
    () => [...commandSections, ...channelSections, ...taskSections],
    [commandSections, channelSections, taskSections],
  );

  const allCommands = useMemo(
    () => sections.flatMap((s) => s.items),
    [sections],
  );

  const handleSelect = (id: string | null): void => {
    if (id === null) return;
    const cmd = allCommands.find((c) => c.id === id);
    if (!cmd) return;
    track(ANALYTICS_EVENTS.COMMAND_MENU_ACTION, {
      action_type: cmd.action,
      channel_id: cmd.channelId,
    });
    cmd.onRun();
    onOpenChange(false);
    setQuery("");
  };

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
          autoHighlight="always"
          keepHighlight
          onValueChange={(val, eventDetails) => {
            if (eventDetails.reason !== "input-change") return;
            if (typeof val === "string") {
              setQuery(val);
            }
          }}
          filter={(cmd, q) => {
            if (!q) return true;
            const haystack = `${cmd.label} ${cmd.keywords ?? ""}`.toLowerCase();
            return haystack.includes(q.toLowerCase());
          }}
        >
          <AutocompleteInput
            placeholder={
              bluebirdEnabled
                ? "Search commands, channels, and tasks…"
                : "Search commands and tasks…"
            }
            autoFocus
            showClear
          />
          <AutocompleteStatus
            emptyContent={
              <span>
                No results for <strong>"{query}"</strong>
              </span>
            }
          />
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
                      // Long task names wrap instead of truncating, so the
                      // item must grow: min-height, not a fixed height. Quill
                      // wraps our children in an inner content span; force it to
                      // fill the row (so a trailing shortcut can `ml-auto` to the
                      // end) and let it overflow visibly so the shortcut Kbd
                      // boxes aren't clipped by the wrapper's `truncate`.
                      className="flex h-auto! min-h-7 w-full items-center gap-2 py-1.5 pr-2 text-left [&>span]:w-full [&>span]:overflow-visible"
                    >
                      {cmd.icon}
                      <span className="wrap-break-word min-w-0 whitespace-normal">
                        {cmd.label}
                      </span>
                      {cmd.detail && (
                        <span className="shrink-0 text-gray-9">
                          · #{cmd.detail}
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
        <CommandKeyHints />
      </DialogContent>
    </Dialog>
  );
}
