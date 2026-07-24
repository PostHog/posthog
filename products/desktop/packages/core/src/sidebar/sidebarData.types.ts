import type { WorkspaceMode } from "@posthog/shared";
import type { TaskRunStatus } from "@posthog/shared/domain-types";
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
  needsPermission: boolean;
  repository: TaskRepositoryInfo | null;
  isSuspended: boolean;
  folderId?: string;
  taskRunStatus?: TaskRunStatus;
  taskRunEnvironment?: "local" | "cloud";
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
