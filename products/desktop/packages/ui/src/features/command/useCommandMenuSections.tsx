import {
  ArchiveIcon,
  CaretLeftIcon,
  CaretRightIcon,
  ChartLine,
  ChatCircleDots,
  CubeIcon,
  EnvelopeSimple,
  Gauge,
  GitDiffIcon,
  HashIcon,
  SquaresFourIcon,
} from "@phosphor-icons/react";
import { workspaceIdSet } from "@posthog/core/command-center/eligibility";
import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import type { CommandMenuAction } from "@posthog/shared/analytics-events";
import type { Task } from "@posthog/shared/domain-types";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import { TaskCommandIcon } from "@posthog/ui/features/command/TaskCommandIcon";
import type {
  Command,
  CommandSection,
} from "@posthog/ui/features/command/useSearchSections";
import type { SettingsCategory } from "@posthog/ui/features/settings/types";
import { LoopIcon } from "@posthog/ui/primitives/LoopIcon";
import {
  goBackInHistory,
  goForwardInHistory,
  navigateToArchived,
  navigateToChannel,
  navigateToCommandCenter,
  navigateToInbox,
  navigateToLoops,
} from "@posthog/ui/router/navigationBridge";
import { openTask, openTaskInput } from "@posthog/ui/router/useOpenTask";
import { showLogFolder } from "@posthog/ui/shell/openExternal";
import type { ThemePreference } from "@posthog/ui/shell/themeStore";
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
import { useMemo } from "react";

interface CommandMenuFolder {
  id: string;
  name: string;
  path: string;
}

interface CommandMenuChannel {
  id: string;
  name: string;
  channelType?: string | null;
}

interface UseCommandMenuSectionsOptions {
  archivedTaskIds: Set<string>;
  bluebirdEnabled: boolean;
  canArchiveTask: boolean;
  canSearchFiles: boolean;
  channels: CommandMenuChannel[];
  closeSettingsDialog: () => void;
  folders: CommandMenuFolder[];
  inboxAvailable: boolean;
  loopsEnabled: boolean;
  onCreateChannel: () => void;
  openFeedback: () => void;
  openFilePicker: () => void;
  openReviewPanel: () => void;
  openSettingsDialog: (category?: SettingsCategory) => void;
  provisioningTaskIds: Set<string>;
  requestArchive: () => void;
  reviewTaskId?: string;
  setTheme: (theme: ThemePreference) => void;
  spacesLayout: boolean;
  spendAnalysisEnabled: boolean;
  systemPrefersDark: boolean;
  tasks: Task[];
  theme: ThemePreference;
  toggleLeftSidebar: () => void;
  workspaces?: Record<string, unknown>;
  workspacesFetched: boolean;
}

export function useCommandMenuSections({
  archivedTaskIds,
  bluebirdEnabled,
  canArchiveTask,
  canSearchFiles,
  channels,
  closeSettingsDialog,
  folders,
  inboxAvailable,
  loopsEnabled,
  onCreateChannel,
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
}: UseCommandMenuSectionsOptions): {
  channelSections: CommandSection[];
  commandSections: CommandSection[];
  taskSections: CommandSection[];
} {
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
      ...(inboxAvailable
        ? [
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
          ]
        : []),
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
      ...(bluebirdEnabled
        ? [
            {
              id: "create-channel",
              label: spacesLayout ? "New space" : "New channel",
              keywords: "create add space channel context",
              icon: spacesLayout ? (
                <CubeIcon size={12} className="text-gray-11" />
              ) : (
                <HashIcon size={12} className="text-gray-11" />
              ),
              action: "create-channel" as CommandMenuAction,
              onRun: () => {
                closeSettingsDialog();
                onCreateChannel();
              },
            },
          ]
        : []),
      {
        id: "toggle-left-sidebar",
        label: "Toggle left sidebar",
        icon: <ViewVerticalIcon className="h-3 w-3 text-gray-11" />,
        action: "toggle-left-sidebar",
        shortcut: SHORTCUTS.TOGGLE_LEFT_SIDEBAR,
        onRun: toggleLeftSidebar,
      },
      {
        id: "send-feedback",
        label: "Send feedback",
        keywords: "report issue bug screenshot logs",
        icon: <ChatCircleDots size={12} className="text-gray-11" />,
        action: "send-feedback",
        shortcut: SHORTCUTS.SEND_FEEDBACK,
        onRun: openFeedback,
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
      ...(canArchiveTask
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

    const sections: CommandSection[] = [
      { label: "Actions", items: actions },
      { label: "Navigation", items: navigation },
      { label: "View", items: viewCommands },
      { label: "Developer", items: developer },
    ];

    if (folders.length > 0) {
      sections.push({
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

    return sections;
  }, [
    bluebirdEnabled,
    canArchiveTask,
    canSearchFiles,
    closeSettingsDialog,
    folders,
    inboxAvailable,
    loopsEnabled,
    onCreateChannel,
    openFeedback,
    openFilePicker,
    openReviewPanel,
    openSettingsDialog,
    requestArchive,
    reviewTaskId,
    spacesLayout,
    spendAnalysisEnabled,
    themeOptions,
    toggleLeftSidebar,
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
            keywords: channel?.name,
            icon: <TaskCommandIcon task={task} />,
            action: "open-task" as CommandMenuAction,
            channelId: bluebirdEnabled ? channel?.id : undefined,
            onRun: () => {
              closeSettingsDialog();
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
    archivedTaskIds,
    bluebirdEnabled,
    channels,
    closeSettingsDialog,
    provisioningTaskIds,
    tasks,
    workspaces,
    workspacesFetched,
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

  return { channelSections, commandSections, taskSections };
}
