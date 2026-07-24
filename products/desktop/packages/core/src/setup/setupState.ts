import type { DiscoveredTask } from "@posthog/core/setup/types";

export type DiscoveryStatus = "idle" | "running" | "done" | "error";
export type EnricherStatus = "idle" | "running" | "done" | "error";

export interface ActivityEntry {
  id: number;
  toolCallId: string;
  tool: string;
  filePath: string | null;
  title: string;
}

export interface AgentFeedState {
  currentTool: string | null;
  currentFilePath: string | null;
  recentEntries: ActivityEntry[];
}

export interface RepoDiscoveryState {
  status: DiscoveryStatus;
  taskId: string | null;
  taskRunId: string | null;
  feed: AgentFeedState;
  error: string | null;
}

export interface RepoEnricherState {
  status: EnricherStatus;
}

export interface SetupStoreState {
  discoveredTasks: DiscoveredTask[];
  discoveryByRepo: Record<string, RepoDiscoveryState>;
  enricherByRepo: Record<string, RepoEnricherState>;
}

export const EMPTY_FEED: AgentFeedState = {
  currentTool: null,
  currentFilePath: null,
  recentEntries: [],
};

export const DEFAULT_DISCOVERY: RepoDiscoveryState = {
  status: "idle",
  taskId: null,
  taskRunId: null,
  feed: EMPTY_FEED,
  error: null,
};

export const DEFAULT_ENRICHER: RepoEnricherState = { status: "idle" };

export const INITIAL_SETUP_STATE: SetupStoreState = {
  discoveredTasks: [],
  discoveryByRepo: {},
  enricherByRepo: {},
};

export function selectRepoDiscovery(
  state: SetupStoreState,
  repoPath: string | null,
): RepoDiscoveryState {
  if (!repoPath) return DEFAULT_DISCOVERY;
  return state.discoveryByRepo[repoPath] ?? DEFAULT_DISCOVERY;
}

export function selectRepoEnricher(
  state: SetupStoreState,
  repoPath: string | null,
): RepoEnricherState {
  if (!repoPath) return DEFAULT_ENRICHER;
  return state.enricherByRepo[repoPath] ?? DEFAULT_ENRICHER;
}

export function isTaskForRepo(
  task: DiscoveredTask,
  repoPath: string | null,
): boolean {
  if (!repoPath) return !task.repoPath;
  return task.repoPath === repoPath;
}

export function dropAgentTasksForRepo(
  tasks: DiscoveredTask[],
  repoPath: string,
): DiscoveredTask[] {
  return tasks.filter(
    (t) => !(t.source === "agent" && isTaskForRepo(t, repoPath)),
  );
}

export function pushEntry(
  prev: AgentFeedState,
  entry: ActivityEntry,
): AgentFeedState {
  const existingIdx = entry.toolCallId
    ? prev.recentEntries.findIndex((e) => e.toolCallId === entry.toolCallId)
    : -1;

  let newEntries: ActivityEntry[];
  if (existingIdx >= 0) {
    newEntries = [...prev.recentEntries];
    const old = newEntries[existingIdx];
    newEntries[existingIdx] = {
      ...old,
      tool: entry.tool || old.tool,
      filePath: entry.filePath || old.filePath,
      title: entry.title || old.title,
    };
  } else {
    newEntries = [...prev.recentEntries.slice(-4), entry];
  }

  return {
    currentTool: entry.tool,
    currentFilePath: entry.filePath ?? prev.currentFilePath,
    recentEntries: newEntries,
  };
}

export function updateDiscovery(
  state: SetupStoreState,
  repoPath: string,
  patch: Partial<RepoDiscoveryState>,
): Record<string, RepoDiscoveryState> {
  const prev = state.discoveryByRepo[repoPath] ?? DEFAULT_DISCOVERY;
  return { ...state.discoveryByRepo, [repoPath]: { ...prev, ...patch } };
}

export function updateEnricher(
  state: SetupStoreState,
  repoPath: string,
  patch: Partial<RepoEnricherState>,
): Record<string, RepoEnricherState> {
  const prev = state.enricherByRepo[repoPath] ?? DEFAULT_ENRICHER;
  return { ...state.enricherByRepo, [repoPath]: { ...prev, ...patch } };
}

export function migrateSetupState(
  persistedState: unknown,
  version: number,
): SetupStoreState {
  if (version < 2) {
    const oldState = (persistedState ?? {}) as {
      discoveryStatus?: string;
      error?: unknown;
    };
    let sentinel: Record<string, RepoDiscoveryState> = {};
    if (oldState.discoveryStatus === "done") {
      sentinel = {
        __migrated_v1__: { ...DEFAULT_DISCOVERY, status: "done" },
      };
    } else if (
      oldState.discoveryStatus === "error" ||
      oldState.discoveryStatus === "running"
    ) {
      sentinel = {
        __migrated_v1__: {
          ...DEFAULT_DISCOVERY,
          status: "error",
          error:
            typeof oldState.error === "string"
              ? oldState.error
              : "Discovery was interrupted. You can skip or retry.",
        },
      };
    }
    return {
      discoveredTasks: [],
      discoveryByRepo: sentinel,
      enricherByRepo: {},
    };
  }
  return persistedState as SetupStoreState;
}

export function partializeSetupState(state: SetupStoreState): SetupStoreState {
  return {
    discoveredTasks: state.discoveredTasks,
    discoveryByRepo: Object.fromEntries(
      Object.entries(state.discoveryByRepo)
        .filter(([, d]) => d.status !== "idle")
        .map(([repo, d]) => {
          if (d.status === "running") {
            return [
              repo,
              {
                ...DEFAULT_DISCOVERY,
                status: "error",
                error: "Discovery was interrupted. You can skip or retry.",
              },
            ];
          }
          return [
            repo,
            { ...DEFAULT_DISCOVERY, status: d.status, error: d.error },
          ];
        }),
    ),
    enricherByRepo: Object.fromEntries(
      Object.entries(state.enricherByRepo).filter(
        ([, e]) => e.status === "done",
      ),
    ),
  };
}
