import type { WorkspaceMode } from "@posthog/shared";
import type { TaskRunStatus } from "@posthog/shared/domain-types";
import type { RunMode } from "./buildSidebarData";
import type {
  TaskGroup as GenericTaskGroup,
  TaskRepositoryInfo,
} from "./groupTasks";

export interface TaskData {
  id: string;
  title: string;
  createdAt: number;
  lastActivityAt: number;
  isGenerating: boolean;
  isUnread: boolean;
  isPinned: boolean;
  /** A live session in this app is holding a prompt only this app can answer. */
  needsPermission: boolean;
  /**
   * The run is blocked on a question to the user, as the backend reports it. This is the only
   * route for a task no session in this app is attached to: the agent's prompts live in the
   * run's log, so without one the row would read as plain "working".
   */
  awaitsInput: boolean;
  repository: TaskRepositoryInfo | null;
  isSuspended: boolean;
  folderId?: string;
  taskRunStatus?: TaskRunStatus;
  taskRunEnvironment?: "local" | "cloud";
  runMode?: RunMode;
  workspaceMode?: WorkspaceMode;
  originProduct?: string;
  slackThreadUrl?: string;
  folderPath: string | null;
  cloudPrUrl: string | null;
  branchName: string | null;
  linkedBranch: string | null;
}

export type TaskGroup = GenericTaskGroup<TaskData>;

export interface SidebarData {
  isHomeActive: boolean;
  isInboxActive: boolean;
  isAgentsActive: boolean;
  isCommandCenterActive: boolean;
  isSkillsActive: boolean;
  isMcpServersActive: boolean;
  isLoading: boolean;
  activeTaskId: string | null;
  pinnedTasks: TaskData[];
  flatTasks: TaskData[];
  groupedTasks: TaskGroup[];
  totalCount: number;
  hasMore: boolean;
}
