import { createStore } from "zustand/vanilla";
import {
  type AutoresearchEndReason,
  type AutoresearchInterruptionReason,
  type AutoresearchIteration,
  type AutoresearchPauseInterval,
  type AutoresearchPhase,
  type AutoresearchResearchFinding,
  type AutoresearchRun,
  type AutoresearchRunStatus,
  isTerminalRunStatus,
} from "./schemas";

export interface AutoresearchState {
  /** Runs indexed by run id. */
  runs: Record<string, AutoresearchRun>;
  /** taskId -> id of the most recently started run for that task. */
  activeRunIdByTask: Record<string, string>;
}

export const autoresearchStore = createStore<AutoresearchState>(() => ({
  runs: {},
  activeRunIdByTask: {},
}));

function updateRun(
  runId: string,
  update: (run: AutoresearchRun) => AutoresearchRun,
): void {
  autoresearchStore.setState((state) => {
    const run = state.runs[runId];
    if (!run) return state;
    return { runs: { ...state.runs, [runId]: update(run) } };
  });
}

export const autoresearchStoreActions = {
  upsertRun(run: AutoresearchRun): void {
    autoresearchStore.setState((state) => ({
      runs: { ...state.runs, [run.id]: run },
      activeRunIdByTask: {
        ...state.activeRunIdByTask,
        [run.config.taskId]: run.id,
      },
    }));
  },

  appendIteration(runId: string, iteration: AutoresearchIteration): void {
    updateRun(runId, (run) => ({
      ...run,
      iterations: [...run.iterations, iteration],
    }));
  },

  appendResearchFinding(
    runId: string,
    finding: AutoresearchResearchFinding,
  ): void {
    updateRun(runId, (run) => ({
      ...run,
      researchFindings: [...run.researchFindings, finding],
    }));
  },

  /** Record the metric label the agent chose in its reports. */
  setMetricName(runId: string, metricName: string): void {
    updateRun(runId, (run) => ({ ...run, metricName }));
  },

  /** Record the metric unit the agent chose in its reports. */
  setMetricUnit(runId: string, metricUnit: string): void {
    updateRun(runId, (run) => ({ ...run, metricUnit }));
  },

  setPhase(runId: string, phase: AutoresearchPhase | null): void {
    updateRun(runId, (run) => ({ ...run, phase }));
  },

  setPauseTiming(
    runId: string,
    pausedAt: number | null,
    pausedDurationMs: number,
    pauseIntervals: AutoresearchPauseInterval[],
  ): void {
    updateRun(runId, (run) => ({
      ...run,
      pausedAt,
      pausedDurationMs,
      pauseIntervals,
    }));
  },

  setRunStatus(
    runId: string,
    status: AutoresearchRunStatus,
    options?: {
      endReason?: AutoresearchEndReason;
      interruptedReason?: AutoresearchInterruptionReason;
      lastError?: string;
    },
  ): void {
    const terminal = isTerminalRunStatus(status);
    updateRun(runId, (run) => ({
      ...run,
      status,
      endedAt: terminal ? Date.now() : run.endedAt,
      endReason: options?.endReason ?? (terminal ? run.endReason : null),
      interruptedReason:
        status === "interrupted"
          ? (options?.interruptedReason ?? run.interruptedReason)
          : null,
      lastError:
        options?.lastError ?? (status === "running" ? null : run.lastError),
    }));
  },

  /**
   * Merge persisted runs into the store. In-memory runs win over their
   * stored counterparts (they are strictly fresher); the active run per task
   * is recomputed as the most recently started one.
   */
  hydrateRuns(hydrated: AutoresearchRun[]): void {
    if (hydrated.length === 0) return;
    autoresearchStore.setState((state) => {
      const runs = { ...state.runs };
      for (const run of hydrated) {
        if (!runs[run.id]) runs[run.id] = run;
      }
      const activeRunIdByTask = { ...state.activeRunIdByTask };
      for (const taskId of new Set(hydrated.map((r) => r.config.taskId))) {
        const newest = Object.values(runs)
          .filter((run) => run.config.taskId === taskId)
          .sort((a, b) => b.startedAt - a.startedAt)[0];
        if (newest) activeRunIdByTask[taskId] = newest.id;
      }
      return { runs, activeRunIdByTask };
    });
  },

  reset(): void {
    autoresearchStore.setState({ runs: {}, activeRunIdByTask: {} });
  },
};

export function getActiveRunForTask(
  state: AutoresearchState,
  taskId: string,
): AutoresearchRun | null {
  const runId = state.activeRunIdByTask[taskId];
  return runId ? (state.runs[runId] ?? null) : null;
}
