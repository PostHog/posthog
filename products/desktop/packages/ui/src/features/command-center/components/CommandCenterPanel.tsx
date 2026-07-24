import {
  ArrowsOut,
  Cloud,
  Desktop,
  Folder,
  GitFork,
  Lightning,
  Plus,
  Terminal,
  X,
} from "@phosphor-icons/react";
import { isBrainrotCell } from "@posthog/core/command-center/grid";
import { ANALYTICS_EVENTS, type WorkspaceMode } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { destroyShellTerminal } from "@posthog/ui/features/terminal/destroyShellTerminal";
import { ShellTerminal } from "@posthog/ui/features/terminal/ShellTerminal";
import { openTask } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import { secureRandomString } from "@posthog/ui/utils/random";
import { Flex, Spinner, Text } from "@radix-ui/themes";
import { useCallback, useEffect, useRef, useState } from "react";
import { useFolders } from "../../folders/useFolders";
import { useCloudPrUrl } from "../../git-interaction/useCloudPrUrl";
import { useDraftStore } from "../../message-editor/draftStore";
import { EmbeddedSessionView } from "../../sessions/components/EmbeddedSessionView";
import { TaskIcon } from "../../sidebar/components/items/TaskIcon";
import { useTaskPrStatus } from "../../sidebar/useTaskPrStatus";
import { TaskInput } from "../../task-detail/components/TaskInput";
import { getCellSessionId, useCommandCenterStore } from "../commandCenterStore";
import type {
  CellStatus,
  CommandCenterCellData,
} from "../hooks/useCommandCenterData";
import { useElementOrientation } from "../hooks/useElementOrientation";
import { getTerminalCellStateKey } from "../terminalCells";
import { CommandCenterPRButton } from "./CommandCenterPRButton";
import { TaskSelector } from "./TaskSelector";

interface CommandCenterPanelProps {
  cell: CommandCenterCellData;
  isActiveSession: boolean;
}

const environmentConfig: Record<
  WorkspaceMode,
  { label: string; icon: typeof Desktop }
> = {
  local: { label: "Local", icon: Desktop },
  worktree: { label: "Worktree", icon: GitFork },
  cloud: { label: "Cloud", icon: Cloud },
};

const STATUS_LABEL: Record<CellStatus, string | null> = {
  running: "Running",
  waiting: "Waiting",
  idle: "Idle",
  completed: "Completed",
  error: null,
};

function CellStatusBadge({
  cell,
}: {
  cell: CommandCenterCellData & { task: Task };
}) {
  const { task, session, workspaceMode, status } = cell;
  const isCloud = workspaceMode === "cloud";
  const cloudPrUrl = useCloudPrUrl(task.id);
  const { prState, hasDiff } = useTaskPrStatus({
    id: task.id,
    cloudPrUrl,
    taskRunEnvironment: task.latest_run?.environment,
  });

  const label = STATUS_LABEL[status];
  if (label === null) return null;

  const taskRunStatus = isCloud
    ? (session?.cloudStatus ?? task.latest_run?.status ?? undefined)
    : undefined;

  return (
    <span className="inline-flex items-center gap-0.5 rounded bg-gray-3 px-1 py-0.5 text-[10px] text-gray-11">
      <TaskIcon
        workspaceMode={workspaceMode ?? undefined}
        isGenerating={session?.isPromptPending}
        needsPermission={(session?.pendingPermissions?.size ?? 0) > 0}
        taskRunStatus={taskRunStatus}
        prState={prState}
        hasDiff={hasDiff}
        size={10}
      />
      {label}
    </span>
  );
}

function EnvironmentBadge({ mode }: { mode: WorkspaceMode | null }) {
  if (!mode) return null;
  const config = environmentConfig[mode];
  const Icon = config.icon;
  return (
    <span className="inline-flex items-center gap-0.5 rounded bg-gray-3 px-1 py-0.5 text-[10px] text-gray-10">
      <Icon size={10} />
      {config.label}
    </span>
  );
}

function EmptyCell({ cellIndex }: { cellIndex: number }) {
  const [selectorOpen, setSelectorOpen] = useState(false);
  // The command-center terminal is unavailable on cloud-only hosts.
  const { localWorkspaces } = useHostCapabilities();
  const isCreating = useCommandCenterStore((s) =>
    s.creatingCells.includes(cellIndex),
  );
  const assignTask = useCommandCenterStore((s) => s.assignTask);
  const setBrainrotCell = useCommandCenterStore((s) => s.setBrainrotCell);
  const setTerminalCell = useCommandCenterStore((s) => s.setTerminalCell);
  const startCreating = useCommandCenterStore((s) => s.startCreating);
  const stopCreating = useCommandCenterStore((s) => s.stopCreating);
  const layout = useCommandCenterStore((s) => s.layout);
  const cells = useCommandCenterStore((s) => s.cells);
  const brainrotMode = useSettingsStore((s) => s.brainrotMode);
  const clearDraft = useDraftStore((s) => s.actions.setDraft);

  const sessionId = getCellSessionId(cellIndex);

  const handleBrainrot = useCallback(() => {
    track(ANALYTICS_EVENTS.BRAINROT_ACTIVATED, {
      layout,
      filled_cells: cells.filter((c) => c && !isBrainrotCell(c)).length,
    });
    setBrainrotCell(cellIndex);
  }, [layout, cells, setBrainrotCell, cellIndex]);

  const handleNewTerminal = useCallback(
    (cwd?: string) => {
      setTerminalCell(cellIndex, secureRandomString(8), cwd);
    },
    [setTerminalCell, cellIndex],
  );

  const handleTaskCreated = useCallback(
    (task: Task) => {
      assignTask(cellIndex, task.id);
      clearDraft(sessionId, null);
    },
    [assignTask, cellIndex, clearDraft, sessionId],
  );

  const handleCancel = useCallback(() => {
    stopCreating(cellIndex);
    clearDraft(sessionId, null);
  }, [stopCreating, cellIndex, clearDraft, sessionId]);

  const wasCreatingRef = useRef(false);
  useEffect(() => {
    if (wasCreatingRef.current && !isCreating) {
      clearDraft(sessionId, null);
    }
    wasCreatingRef.current = isCreating;
  }, [isCreating, clearDraft, sessionId]);

  if (isCreating) {
    return (
      <Flex direction="column" height="100%">
        <Flex
          align="center"
          justify="between"
          px="2"
          py="1"
          className="shrink-0 border-gray-6 border-b"
        >
          <Text className="font-medium font-mono text-[11px] text-gray-11">
            New task
          </Text>
          <button
            type="button"
            onClick={handleCancel}
            className="flex h-5 w-5 items-center justify-center rounded text-gray-10 transition-colors hover:bg-gray-4 hover:text-gray-12"
            title="Cancel"
          >
            <X size={12} />
          </button>
        </Flex>
        <Flex direction="column" className="min-h-0 flex-1">
          <TaskInput sessionId={sessionId} onTaskCreated={handleTaskCreated} />
        </Flex>
      </Flex>
    );
  }

  return (
    <Flex align="center" justify="center" height="100%">
      <Flex direction="column" align="center" gap="2" className="select-none">
        <TaskSelector
          cellIndex={cellIndex}
          open={selectorOpen}
          onOpenChange={setSelectorOpen}
          onNewTask={() => startCreating(cellIndex)}
          onNewTerminal={localWorkspaces ? handleNewTerminal : undefined}
          onBrainrot={brainrotMode ? handleBrainrot : undefined}
        >
          <button
            type="button"
            onClick={() => setSelectorOpen(true)}
            className="flex items-center gap-1.5 rounded-md border border-gray-7 border-dashed px-3 py-1.5 text-[12px] text-gray-10 transition-colors hover:border-gray-9 hover:text-gray-12"
          >
            <Plus size={12} />
            Add task
          </button>
        </TaskSelector>
        <Text className="text-[11px] text-gray-9">
          or drag a task from the sidebar
        </Text>
      </Flex>
    </Flex>
  );
}

const BRAINROT_LANDSCAPE_URL =
  "https://res.cloudinary.com/dmukukwp6/video/upload/brainrot_landscape_051f419306.mp4";
const BRAINROT_PORTRAIT_URL =
  "https://res.cloudinary.com/dmukukwp6/video/upload/brainrot_portrait_0f14096e6a.mp4";

function BrainrotCell({ cellIndex }: { cellIndex: number }) {
  const clearCell = useCommandCenterStore((s) => s.clearCell);
  const stageRef = useRef<HTMLDivElement>(null);
  const orientation = useElementOrientation(stageRef);
  const src =
    orientation === "portrait" ? BRAINROT_PORTRAIT_URL : BRAINROT_LANDSCAPE_URL;
  const [loading, setLoading] = useState(true);

  return (
    <Flex direction="column" height="100%">
      <Flex
        align="center"
        gap="2"
        px="2"
        py="1"
        className="shrink-0 border-gray-6 border-b"
      >
        <Lightning size={12} weight="fill" className="shrink-0 text-amber-9" />
        <Text className="min-w-0 flex-1 truncate font-medium text-[12px]">
          Brainrot
        </Text>
        <button
          type="button"
          onClick={() => clearCell(cellIndex)}
          className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-gray-10 transition-colors hover:bg-gray-4 hover:text-gray-12"
          title="Remove from grid"
        >
          <X size={12} />
        </button>
      </Flex>
      <div
        ref={stageRef}
        className="relative min-h-0 flex-1 overflow-hidden bg-black"
      >
        <video
          key={orientation}
          src={src}
          aria-label="Brainrot"
          autoPlay
          loop
          muted
          playsInline
          onLoadStart={() => setLoading(true)}
          onCanPlay={() => setLoading(false)}
          className="h-full w-full object-contain"
        />
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center text-gray-11">
            <Spinner size="3" />
          </div>
        )}
      </div>
    </Flex>
  );
}

function TerminalCell({
  cellIndex,
  terminalId,
  terminalCwd,
}: {
  cellIndex: number;
  terminalId: string;
  terminalCwd: string | null;
}) {
  const clearCell = useCommandCenterStore((s) => s.clearCell);
  const { getRecentFolders, getFolderDisplayName } = useFolders();
  const cwd = terminalCwd ?? getRecentFolders(1)[0]?.path;
  const folderName = cwd ? getFolderDisplayName(cwd) : null;
  const stateKey = getTerminalCellStateKey(terminalId);

  const handleRemove = useCallback(() => {
    destroyShellTerminal(stateKey);
    clearCell(cellIndex);
  }, [stateKey, clearCell, cellIndex]);

  return (
    <Flex direction="column" height="100%">
      <Flex
        align="center"
        gap="2"
        px="2"
        py="1"
        className="shrink-0 border-gray-6 border-b"
      >
        <Terminal size={12} className="shrink-0 text-gray-10" />
        <Text className="min-w-0 flex-1 truncate font-medium text-[12px]">
          Terminal
        </Text>
        {folderName && (
          <span className="inline-flex items-center gap-0.5 rounded bg-gray-3 px-1 py-0.5 text-[10px] text-gray-10">
            <Folder size={10} />
            {folderName}
          </span>
        )}
        <button
          type="button"
          onClick={handleRemove}
          className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-gray-10 transition-colors hover:bg-gray-4 hover:text-gray-12"
          title="Remove from grid"
        >
          <X size={12} />
        </button>
      </Flex>
      <Flex direction="column" className="min-h-0 flex-1">
        <ShellTerminal cwd={cwd} stateKey={stateKey} />
      </Flex>
    </Flex>
  );
}

function PopulatedCell({
  cell,
  isActiveSession,
}: {
  cell: CommandCenterCellData & { task: Task };
  isActiveSession: boolean;
}) {
  const clearCell = useCommandCenterStore((s) => s.clearCell);

  const handleExpand = useCallback(() => {
    void openTask(cell.task);
  }, [cell.task]);

  const handleRemove = useCallback(() => {
    clearCell(cell.cellIndex);
  }, [clearCell, cell.cellIndex]);

  return (
    <Flex direction="column" height="100%">
      <Flex
        align="center"
        gap="2"
        px="2"
        py="1"
        className="shrink-0 border-gray-6 border-b"
      >
        <Text
          className="min-w-0 flex-1 truncate font-medium text-[12px]"
          title={cell.task.title}
        >
          {cell.task.title}
        </Text>
        <Flex align="center" gap="1" className="shrink-0">
          <CellStatusBadge cell={cell} />
          <EnvironmentBadge mode={cell.workspaceMode} />
          {cell.repoName && (
            <span className="inline-flex items-center gap-0.5 rounded bg-gray-3 px-1 py-0.5 text-[10px] text-gray-10">
              <Folder size={10} />
              {cell.repoName}
            </span>
          )}
          <CommandCenterPRButton
            taskId={cell.task.id}
            workspaceMode={cell.workspaceMode}
          />
          <button
            type="button"
            onClick={handleExpand}
            className="flex h-5 w-5 items-center justify-center rounded text-gray-10 transition-colors hover:bg-gray-4 hover:text-gray-12"
            title="Open task"
          >
            <ArrowsOut size={12} />
          </button>
          <button
            type="button"
            onClick={handleRemove}
            className="flex h-5 w-5 items-center justify-center rounded text-gray-10 transition-colors hover:bg-gray-4 hover:text-gray-12"
            title="Remove from grid"
          >
            <X size={12} />
          </button>
        </Flex>
      </Flex>

      <Flex direction="column" className="min-h-0 flex-1">
        <EmbeddedSessionView
          task={cell.task}
          isActiveSession={isActiveSession}
        />
      </Flex>
    </Flex>
  );
}

export function CommandCenterPanel({
  cell,
  isActiveSession,
}: CommandCenterPanelProps) {
  if (cell.isBrainrot) {
    return <BrainrotCell cellIndex={cell.cellIndex} />;
  }

  if (cell.terminalId) {
    return (
      <TerminalCell
        cellIndex={cell.cellIndex}
        terminalId={cell.terminalId}
        terminalCwd={cell.terminalCwd}
      />
    );
  }

  if (!cell.taskId || !cell.task) {
    return <EmptyCell cellIndex={cell.cellIndex} />;
  }

  return (
    <PopulatedCell
      cell={cell as CommandCenterCellData & { task: Task }}
      isActiveSession={isActiveSession}
    />
  );
}
