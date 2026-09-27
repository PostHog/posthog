import { createAppendOnlyTracker } from "@posthog/core/sessions/appendOnlyTracker";
import { sessionStore } from "@posthog/core/sessions/sessionStore";
import { readToolCallUpdate } from "@posthog/core/sessions/toolCallUpdates";
import type { AcpMessage } from "@posthog/shared";
import {
  isTerminalStatus,
  type Task,
  type TaskRun,
  type TaskRunExposedPort,
} from "@posthog/shared/domain-types";
import { inject, injectable } from "inversify";

export const EXPOSE_PORT_TOOL = "expose_port";
export const LOCAL_PREVIEW_RUN_ID = "local";
export const TASK_PREVIEW_PORTS_POLL_INTERVAL_MS = 30_000;

export type TaskPreviewPorts = {
  runId: string;
  ports: TaskRunExposedPort[];
};

export type TaskPreviewPortsSnapshot = TaskPreviewPorts & { settled: boolean };

export interface TaskPreviewPortsHost {
  isPreviewEnabled(): boolean;
  onPreviewEnabledChange(listener: () => void): () => void;
  isCloudTask(task: Task): Promise<boolean>;
  fetchTaskRun(taskId: string, runId: string): Promise<TaskRun | null>;
}

export const TASK_PREVIEW_PORTS_HOST = Symbol.for(
  "posthog.core.taskPreview.portsHost",
);

type ExposedPortState = {
  inputs: Map<string, TaskRunExposedPort>;
  byPort: Map<number, TaskRunExposedPort>;
  completedCalls: number;
  result: TaskRunExposedPort[];
};

type ExposedPortSummary = {
  ports: TaskRunExposedPort[];
  completedCalls: number;
};

function readInput(rawInput: unknown): TaskRunExposedPort | null {
  if (!rawInput || typeof rawInput !== "object") return null;
  const { port, name } = rawInput as { port?: unknown; name?: unknown };
  if (typeof port !== "number" || !Number.isInteger(port)) return null;
  return { port, name: typeof name === "string" && name ? name : null };
}

function createExposedPortTracker() {
  return createAppendOnlyTracker<ExposedPortState, ExposedPortSummary>({
    init: () => ({
      inputs: new Map(),
      byPort: new Map(),
      completedCalls: 0,
      result: [],
    }),
    processEvent: (state, event) => {
      const update = readToolCallUpdate(event);
      if (!update) return;
      if (update.tool === EXPOSE_PORT_TOOL) {
        const input = readInput(update.rawInput);
        if (input) state.inputs.set(update.toolCallId, input);
      }
      const input = state.inputs.get(update.toolCallId);
      if (update.status !== "completed" || !input) return;
      state.completedCalls += 1;
      state.byPort.set(input.port, input);
      state.result = [...state.byPort.values()];
    },
    getResult: (state) => ({
      ports: state.result,
      completedCalls: state.completedCalls,
    }),
  });
}

export function exposedPortsFromEvents(
  events: AcpMessage[],
): TaskRunExposedPort[] {
  return createExposedPortTracker().update(events).ports;
}

function sessionEvents(taskId: string): AcpMessage[] {
  const state = sessionStore.getState();
  const taskRunId = state.taskIdIndex[taskId];
  return (taskRunId ? state.sessions[taskRunId]?.events : undefined) ?? [];
}

@injectable()
export class TaskPreviewPortsService {
  private readonly trackers = new Map<
    string,
    ReturnType<typeof createExposedPortTracker>
  >();

  constructor(
    @inject(TASK_PREVIEW_PORTS_HOST)
    private readonly host: TaskPreviewPortsHost,
  ) {}

  async getPreviewPorts(task: Task): Promise<TaskPreviewPortsSnapshot | null> {
    if (!this.host.isPreviewEnabled()) return null;
    const runId = task.latest_run?.id;
    if (!(await this.host.isCloudTask(task))) {
      return {
        runId: runId ?? LOCAL_PREVIEW_RUN_ID,
        ports: this.exposedPorts(task.id).ports,
        settled: false,
      };
    }
    if (!runId) return null;
    const run = await this.host.fetchTaskRun(task.id, runId);
    const settled = !!run && isTerminalStatus(run.status);
    return {
      runId,
      ports: run && !settled ? (run.exposed_ports ?? []) : [],
      settled,
    };
  }

  watch(onChange: (taskId: string | null) => void): () => void {
    const completedCalls = new Map<string, number>();
    const stopSessions = sessionStore.subscribe((state) => {
      for (const taskId of Object.keys(state.taskIdIndex)) {
        const count = this.exposedPorts(taskId).completedCalls;
        const previous = completedCalls.get(taskId) ?? 0;
        if (count === previous) continue;
        completedCalls.set(taskId, count);
        onChange(taskId);
      }
    });
    const stopFlags = this.host.onPreviewEnabledChange(() => onChange(null));
    return () => {
      stopSessions();
      stopFlags();
    };
  }

  private exposedPorts(taskId: string): ExposedPortSummary {
    let tracker = this.trackers.get(taskId);
    if (!tracker) {
      tracker = createExposedPortTracker();
      this.trackers.set(taskId, tracker);
    }
    return tracker.update(sessionEvents(taskId));
  }
}
