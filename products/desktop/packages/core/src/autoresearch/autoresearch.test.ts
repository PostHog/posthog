import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import type { AcpMessage, AgentSession } from "@posthog/shared";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionStore, sessionStoreSetters } from "../sessions/sessionStore";
import {
  AutoresearchService,
  MAX_RECOVERY_ATTEMPTS,
  RECOVERY_BASE_DELAY_MS,
  REMINDER_GRACE_MS,
} from "./autoresearch";
import {
  autoresearchStore,
  autoresearchStoreActions,
  getActiveRunForTask,
} from "./autoresearchStore";
import type { StoredAutoresearchRun } from "./identifiers";
import type { AutoresearchConfigInput, AutoresearchRun } from "./schemas";

const mockLog = {
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
};

let sentPrompts: Array<{ taskId: string; prompt: string }> = [];
let sendPromptImpl: (
  taskId: string,
  prompt: string,
) => Promise<{ stopReason: string }>;
let reconnectCalls: string[] = [];
let reconnectImpl: (taskId: string) => Promise<void>;
let modelSwitches: Array<{ taskId: string; model: string }> = [];
let effortSwitches: Array<{ taskId: string; effort: string }> = [];

const sessionClient = {
  sendPrompt: vi.fn((taskId: string, prompt: string) => {
    sentPrompts.push({ taskId, prompt });
    return sendPromptImpl(taskId, prompt);
  }),
  reconnect: vi.fn((taskId: string) => {
    reconnectCalls.push(taskId);
    return reconnectImpl(taskId);
  }),
  setModel: vi.fn((taskId: string, model: string) => {
    modelSwitches.push({ taskId, model });
    return Promise.resolve();
  }),
  setEffort: vi.fn((taskId: string, effort: string) => {
    effortSwitches.push({ taskId, effort });
    return Promise.resolve();
  }),
};

let gateEnabledImpl: () => Promise<boolean>;

const gateClient = {
  isEnabled: vi.fn(() => gateEnabledImpl()),
};

let savedRuns: StoredAutoresearchRun[] = [];
let listOpenImpl: () => Promise<StoredAutoresearchRun[]>;
let listByTaskImpl: (taskId: string) => Promise<StoredAutoresearchRun[]>;

const storageClient = {
  save: vi.fn((run: StoredAutoresearchRun) => {
    savedRuns.push(run);
    return Promise.resolve();
  }),
  listOpen: vi.fn(() => listOpenImpl()),
  listByTask: vi.fn((taskId: string) => listByTaskImpl(taskId)),
};

function makeService(): AutoresearchService {
  const service = new AutoresearchService();
  const s = service as unknown as Record<string, unknown>;
  s.rootLogger = { ...mockLog, scope: () => mockLog };
  s.sessionClient = sessionClient;
  s.storage = storageClient;
  s.gate = gateClient;
  return service;
}

const TASK_ID = "task-1";
const TASK_RUN_ID = "run-1";

function makeSession(overrides: Partial<AgentSession> = {}): AgentSession {
  return {
    taskRunId: TASK_RUN_ID,
    taskId: TASK_ID,
    taskTitle: "Optimize things",
    channel: "channel",
    events: [],
    startedAt: 0,
    status: "connected",
    isPromptPending: false,
    isCompacting: false,
    promptStartedAt: null,
    pendingPermissions: new Map(),
    pausedDurationMs: 0,
    messageQueue: [],
    optimisticItems: [],
    ...overrides,
  };
}

let eventTs = 0;

function promptEvent(): AcpMessage {
  eventTs += 1;
  return {
    type: "acp_message",
    ts: eventTs,
    message: {
      jsonrpc: "2.0",
      id: eventTs,
      method: "session/prompt",
      params: { prompt: [{ type: "text", text: "go" }] },
    },
  };
}

function agentChunkEvent(text: string): AcpMessage {
  eventTs += 1;
  return {
    type: "acp_message",
    ts: eventTs,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: {
        update: {
          sessionUpdate: "agent_message_chunk",
          content: { type: "text", text },
        },
      },
    },
  };
}

function reportText(value: number, summary = "tweak"): string {
  return `Done.\n\`\`\`autoresearch\nmetric: ${value}\nsummary: ${summary}\n\`\`\``;
}

function researchText(
  summary = "Mapped the execution path",
  finding = "The metric is computed in the workspace server.",
  nextStep = "Trace the benchmark command",
): string {
  return `Investigated.\n\`\`\`autoresearch\ntype: research\nsummary: ${summary}\nfinding: ${finding}\nnext: ${nextStep}\n\`\`\``;
}

/** A session `model` config option (and optional `thought_level`). */
function modelConfig(
  currentValue: string,
  currentEffort?: string,
): SessionConfigOption[] {
  const options = [
    {
      id: "model",
      category: "model",
      name: "Model",
      type: "select",
      currentValue,
      options: [
        { value: currentValue, name: currentValue },
        { value: "claude-opus-4-8", name: "Opus" },
        { value: "claude-haiku-4-5", name: "Haiku" },
      ],
    },
  ];
  if (currentEffort) {
    options.push({
      id: "thought_level",
      category: "thought_level",
      name: "Effort",
      type: "select",
      currentValue: currentEffort,
      options: [
        { value: "low", name: "Low" },
        { value: "high", name: "High" },
        { value: currentEffort, name: currentEffort },
      ],
    });
  }
  return options as SessionConfigOption[];
}

function namedReportText(value: number, name: string): string {
  return `Done.\n\`\`\`autoresearch\nmetric: ${value}\nname: ${name}\nsummary: tweak\n\`\`\``;
}

/** Simulate the agent starting a turn on the task's session. */
function beginTurn(taskRunId = TASK_RUN_ID): void {
  sessionStoreSetters.updateSession(taskRunId, {
    isPromptPending: true,
    events: [
      ...(sessionStore.getState().sessions[taskRunId]?.events ?? []),
      promptEvent(),
    ],
  });
}

/** Simulate the agent finishing a turn that replied with `text`. */
function completeTurn(text: string, taskRunId = TASK_RUN_ID): void {
  const events = sessionStore.getState().sessions[taskRunId]?.events ?? [];
  sessionStoreSetters.updateSession(taskRunId, {
    isPromptPending: false,
    events: [...events, agentChunkEvent(text)],
  });
}

function streamTurnText(text: string, taskRunId = TASK_RUN_ID): void {
  const events = sessionStore.getState().sessions[taskRunId]?.events ?? [];
  sessionStoreSetters.updateSession(taskRunId, {
    isPromptPending: true,
    events: [...events, agentChunkEvent(text)],
  });
}

function runTurn(text: string, taskRunId = TASK_RUN_ID): void {
  beginTurn(taskRunId);
  completeTurn(text, taskRunId);
}

const baseConfig: AutoresearchConfigInput = {
  taskId: TASK_ID,
  direction: "maximize",
  instructions: "Raise the score.",
};

const splitConfig: AutoresearchConfigInput = {
  ...baseConfig,
  implementModel: "claude-opus-4-8",
  measureModel: "claude-haiku-4-5",
};

function activeRun(taskId = TASK_ID): AutoresearchRun {
  const run = getActiveRunForTask(autoresearchStore.getState(), taskId);
  if (!run) throw new Error("expected an active run");
  return run;
}

function makeRun(
  overrides: Partial<Omit<AutoresearchRun, "config">> & {
    config?: Partial<AutoresearchRun["config"]>;
  } = {},
): AutoresearchRun {
  const config: AutoresearchRun["config"] = {
    taskId: TASK_ID,
    direction: "maximize",
    targetValue: null,
    maxIterations: 10,
    implementModel: null,
    measureModel: null,
    implementEffort: null,
    measureEffort: null,
    instructions: "Raise the score.",
  };
  const { config: configOverrides, ...runOverrides } = overrides;
  return {
    id: "ar-stored-1",
    config: { ...config, ...configOverrides },
    status: "running",
    metricName: null,
    metricUnit: null,
    phase: null,
    originalModel: null,
    originalEffort: null,
    researchFindings: [],
    iterations: [],
    startedAt: 1_000,
    pauseIntervals: [],
    endedAt: null,
    endReason: null,
    interruptedReason: null,
    lastError: null,
    ...runOverrides,
  };
}

function storedRow(run: AutoresearchRun): StoredAutoresearchRun {
  return {
    id: run.id,
    taskId: run.config.taskId,
    endedAt: run.endedAt ? new Date(run.endedAt).toISOString() : null,
    data: JSON.stringify(run),
  };
}

const flush = () => vi.advanceTimersByTimeAsync(0);

/** Grace period plus the send microtasks it may trigger. */
const passReminderGrace = () => vi.advanceTimersByTimeAsync(REMINDER_GRACE_MS);
const passRecoveryDelay = (multiplier = 1) =>
  vi.advanceTimersByTimeAsync(RECOVERY_BASE_DELAY_MS * multiplier);

describe("AutoresearchService", () => {
  let service: AutoresearchService;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    sentPrompts = [];
    sendPromptImpl = () => Promise.resolve({ stopReason: "end_turn" });
    reconnectCalls = [];
    reconnectImpl = () => Promise.resolve();
    modelSwitches = [];
    effortSwitches = [];
    gateEnabledImpl = () => Promise.resolve(true);
    savedRuns = [];
    listOpenImpl = () => Promise.resolve([]);
    listByTaskImpl = () => Promise.resolve([]);
    autoresearchStoreActions.reset();
    sessionStore.setState({ sessions: {}, taskIdIndex: {} });
    sessionStoreSetters.setSession(makeSession());
    service = makeService();
  });

  afterEach(() => {
    service.dispose();
    vi.useRealTimers();
  });

  describe("startRun", () => {
    it("registers a running run and sends the kickoff prompt", () => {
      const run = service.startRun(baseConfig);

      expect(run.status).toBe("running");
      expect(activeRun().id).toBe(run.id);
      expect(sentPrompts).toHaveLength(1);
      expect(sentPrompts[0].taskId).toBe(TASK_ID);
      expect(sentPrompts[0].prompt).toContain("autoresearch mode");
      expect(sentPrompts[0].prompt).toContain("```autoresearch");
    });

    it("rejects invalid configs", () => {
      expect(() =>
        service.startRun({ ...baseConfig, instructions: " " }),
      ).toThrow();
      expect(sentPrompts).toHaveLength(0);
    });

    it("refuses to start while a run is live for the task", () => {
      service.startRun(baseConfig);
      expect(() => service.startRun(baseConfig)).toThrow(/already running/);
    });

    it("allows a new run after the previous one ended", () => {
      const first = service.startRun(baseConfig);
      service.stopRun(first.id);

      const second = service.startRun(baseConfig);
      expect(second.id).not.toBe(first.id);
      expect(activeRun().id).toBe(second.id);
    });

    it("interrupts the run when the kickoff prompt cannot be sent", async () => {
      sendPromptImpl = () => Promise.reject(new Error("no session"));
      const run = service.startRun(baseConfig);
      await flush();

      const stored = autoresearchStore.getState().runs[run.id];
      expect(stored?.status).toBe("interrupted");
      expect(stored?.interruptedReason).toBe("send-failed");
      expect(stored?.lastError).toBe("no session");
    });
  });

  describe("registerRun", () => {
    it("registers without sending because the kickoff rode the task initial prompt", () => {
      const run = service.registerRun(baseConfig);

      expect(run.status).toBe("running");
      expect(activeRun().id).toBe(run.id);
      expect(sentPrompts).toHaveLength(0);
    });

    it("takes over the loop from the agent's first reply", () => {
      service.registerRun(baseConfig);
      runTurn(reportText(10, "baseline"));

      expect(activeRun().iterations).toHaveLength(1);
      expect(sentPrompts).toHaveLength(1);
      expect(sentPrompts[0].prompt).toContain("iteration 2");
    });

    it("tracks reports from an initial prompt already in progress", () => {
      beginTurn();
      service.registerRun(baseConfig);

      streamTurnText(`${reportText(10, "baseline")}\nIteration 2 starts now.`);
      streamTurnText(
        `${reportText(12, "iteration 2")}\nIteration 3 starts now.`,
      );
      streamTurnText(
        `${reportText(14, "iteration 3")}\nIteration 4 starts now.`,
      );

      expect(activeRun().iterations).toEqual([
        expect.objectContaining({ index: 1, value: 10 }),
        expect.objectContaining({ index: 2, value: 12 }),
        expect.objectContaining({ index: 3, value: 14 }),
      ]);
      expect(sentPrompts).toHaveLength(0);

      completeTurn("Continuing after the reported iterations.");

      expect(activeRun().iterations).toHaveLength(3);
      expect(sentPrompts).toHaveLength(1);
      expect(sentPrompts[0].prompt).toContain("iteration 4");
    });

    it("recovers when an active prompt was incorrectly marked handled", () => {
      beginTurn();
      const run = service.registerRun(baseConfig);
      const internals = service as unknown as {
        promptCursor: Map<string, number>;
      };
      internals.promptCursor.set(run.id, 1);

      streamTurnText(`${reportText(10, "baseline")}\nIteration 2 starts now.`);

      expect(activeRun().iterations).toEqual([
        expect.objectContaining({ index: 1, value: 10 }),
      ]);
    });

    it("shares the one-live-run-per-task guard with startRun", () => {
      service.registerRun(baseConfig);
      expect(() => service.startRun(baseConfig)).toThrow(/already running/);
    });
  });

  describe("iteration loop", () => {
    it("records a metric block after the next iteration starts", () => {
      service.startRun(baseConfig);
      beginTurn();
      streamTurnText(`${reportText(10, "baseline")}\nIteration 2 starts now.`);

      expect(activeRun().iterations).toEqual([
        expect.objectContaining({ index: 1, value: 10, summary: "baseline" }),
      ]);
      expect(sentPrompts).toHaveLength(1);

      streamTurnText("Continuing to inspect the next change.");
      expect(activeRun().iterations).toHaveLength(1);

      completeTurn("Finished the turn.");
      expect(activeRun().iterations).toHaveLength(1);
      expect(sentPrompts).toHaveLength(2);
      expect(sentPrompts.at(-1)?.prompt).toContain(
        "Then make the next focused change",
      );
    });

    it("keeps the tail report provisional until the turn ends", () => {
      service.startRun({ ...baseConfig, maxIterations: 1 });
      beginTurn();
      streamTurnText(reportText(10, "draft baseline"));

      expect(activeRun().iterations).toHaveLength(0);
      expect(activeRun().status).toBe("running");

      streamTurnText(reportText(12, "corrected baseline"));
      expect(activeRun().iterations).toHaveLength(0);

      completeTurn("Finalized the corrected report.");

      expect(activeRun().iterations).toEqual([
        expect.objectContaining({
          index: 1,
          value: 12,
          summary: "corrected baseline",
        }),
      ]);
      expect(activeRun().status).toBe("completed");
      expect(activeRun().endReason).toBe("max-iterations");
    });

    it("records prebaseline research without consuming an iteration", () => {
      service.startRun(baseConfig);
      runTurn(researchText());

      const researchingRun = activeRun();
      expect(researchingRun.researchFindings).toEqual([
        expect.objectContaining({
          index: 1,
          summary: "Mapped the execution path",
          finding: "The metric is computed in the workspace server.",
          nextStep: "Trace the benchmark command",
        }),
      ]);
      expect(researchingRun.iterations).toHaveLength(0);
      expect(sentPrompts.at(-1)?.prompt).toContain(
        "Continue investigating the codebase or establish the baseline measurement",
      );

      runTurn(reportText(10, "baseline"));

      expect(activeRun().iterations).toEqual([
        expect.objectContaining({ index: 1, value: 10, summary: "baseline" }),
      ]);
    });

    it("does not accept research checkpoints after the baseline", async () => {
      service.startRun(baseConfig);
      runTurn(reportText(10, "baseline"));
      runTurn(researchText());
      await passReminderGrace();

      expect(activeRun().researchFindings).toHaveLength(0);
      expect(activeRun().iterations).toHaveLength(1);
      expect(sentPrompts.at(-1)?.prompt).toContain("did not include");
    });

    it("prefers a metric when a prebaseline reply contains both report types", () => {
      service.startRun(baseConfig);
      runTurn(`${researchText()}\n${reportText(10, "baseline")}`);

      expect(activeRun().researchFindings).toHaveLength(0);
      expect(activeRun().iterations).toEqual([
        expect.objectContaining({ index: 1, value: 10, summary: "baseline" }),
      ]);
    });

    it("records an iteration and sends a continuation prompt", () => {
      service.startRun(baseConfig);
      runTurn(reportText(10, "baseline"));

      const run = activeRun();
      expect(run.iterations).toEqual([
        expect.objectContaining({
          index: 1,
          value: 10,
          bestValue: 10,
          delta: null,
          summary: "baseline",
        }),
      ]);
      expect(sentPrompts).toHaveLength(2);
      expect(sentPrompts[1].prompt).toContain("iteration 2");
      expect(sentPrompts[1].prompt).toContain("Best so far: 10 (iteration 1)");
    });

    it("tracks deltas and direction-aware best across iterations", () => {
      service.startRun({ ...baseConfig, direction: "minimize" });
      runTurn(reportText(100));
      runTurn(reportText(80));
      runTurn(reportText(95));

      const [first, second, third] = activeRun().iterations;
      expect(first).toMatchObject({ value: 100, bestValue: 100, delta: null });
      expect(second).toMatchObject({ value: 80, bestValue: 80, delta: -20 });
      expect(third).toMatchObject({ value: 95, bestValue: 80, delta: 15 });
    });

    it("completes when the target is reached and stops prompting", () => {
      service.startRun({ ...baseConfig, targetValue: 50 });
      runTurn(reportText(30));
      runTurn(reportText(55));

      const run = activeRun();
      expect(run.status).toBe("completed");
      expect(run.endReason).toBe("target-reached");
      expect(run.endedAt).not.toBeNull();
      // kickoff + one continuation after iteration 1, nothing after completion
      expect(sentPrompts).toHaveLength(2);
    });

    it("completes when the iteration budget is spent", () => {
      service.startRun({ ...baseConfig, maxIterations: 2 });
      runTurn(reportText(1));
      runTurn(reportText(2));

      const run = activeRun();
      expect(run.status).toBe("completed");
      expect(run.endReason).toBe("max-iterations");
      expect(sentPrompts).toHaveLength(2);
    });

    it("ignores turns on unrelated tasks", () => {
      sessionStoreSetters.setSession(
        makeSession({ taskId: "task-2", taskRunId: "run-2" }),
      );
      service.startRun(baseConfig);
      runTurn(reportText(10), "run-2");

      expect(activeRun().iterations).toHaveLength(0);
      expect(sentPrompts).toHaveLength(1);
    });

    it("ignores a prompt-pending flip that is not a real turn", () => {
      service.startRun(baseConfig);
      runTurn(reportText(10));
      expect(activeRun().iterations).toHaveLength(1);

      // A failed send flips isPromptPending without adding a session/prompt
      // event. Re-parsing the previous turn here would duplicate iteration 1.
      sessionStoreSetters.updateSession(TASK_RUN_ID, { isPromptPending: true });
      sessionStoreSetters.updateSession(TASK_RUN_ID, {
        isPromptPending: false,
      });

      expect(activeRun().iterations).toHaveLength(1);
      expect(sentPrompts).toHaveLength(2);
      expect(activeRun().status).toBe("running");
    });

    it("does nothing after dispose", () => {
      service.startRun(baseConfig);
      service.dispose();
      runTurn(reportText(10));

      expect(activeRun().iterations).toHaveLength(0);
      expect(sentPrompts).toHaveLength(1);
    });
  });

  describe("missing reports", () => {
    it("reminds the agent once when a turn has no report", async () => {
      service.startRun(baseConfig);
      runTurn("I made a change but forgot to measure.");
      await passReminderGrace();

      const run = activeRun();
      expect(run.status).toBe("running");
      expect(run.iterations).toHaveLength(0);
      expect(sentPrompts).toHaveLength(2);
      expect(sentPrompts[1].prompt).toContain("did not include");
    });

    it("fails the run when the reminder also goes unanswered", async () => {
      service.startRun(baseConfig);
      runTurn("no report");
      await passReminderGrace();
      runTurn("still no report");
      await passReminderGrace();

      const run = activeRun();
      expect(run.status).toBe("failed");
      expect(run.endReason).toBe("missing-report");
    });

    it("recovers when the reminder produces a report", async () => {
      service.startRun(baseConfig);
      runTurn("no report");
      await passReminderGrace();
      runTurn(reportText(42));

      expect(activeRun().status).toBe("running");
      expect(activeRun().iterations).toHaveLength(1);

      // The reminder budget is reset: a later lapse reminds again
      // instead of failing immediately.
      runTurn("oops, no report again");
      await passReminderGrace();
      expect(activeRun().status).toBe("running");
      expect(sentPrompts.at(-1)?.prompt).toContain("did not include");
    });
  });

  describe("metric naming", () => {
    it("adopts the metric name from the first named report", () => {
      service.startRun(baseConfig);
      runTurn(namedReportText(10, "bundle size (kB)"));

      expect(activeRun().metricName).toBe("bundle size (kB)");
      expect(sentPrompts.at(-1)?.prompt).toContain('"bundle size (kB)"');
    });

    it("keeps the first name when later reports rename the metric", () => {
      service.startRun(baseConfig);
      runTurn(namedReportText(10, "bundle size (kB)"));
      runTurn(namedReportText(9, "bundle kilobytes"));

      expect(activeRun().metricName).toBe("bundle size (kB)");
    });

    it("adopts the metric unit from the first report that carries one", () => {
      service.startRun(baseConfig);
      runTurn(
        "```autoresearch\nmetric: 412\nname: bundle size\nunit: kB\nsummary: baseline\n```",
      );
      expect(activeRun().metricUnit).toBe("kB");

      // First unit wins, like the name. A stable unit keeps values readable.
      runTurn("```autoresearch\nmetric: 400000\nunit: bytes\n```");
      expect(activeRun().metricUnit).toBe("kB");
    });

    it("runs unnamed until a report carries a name", () => {
      service.startRun(baseConfig);
      runTurn(reportText(10));

      expect(activeRun().metricName).toBeNull();
      expect(sentPrompts.at(-1)?.prompt).toContain("the metric");

      runTurn(namedReportText(11, "score"));
      expect(activeRun().metricName).toBe("score");
    });
  });

  describe("split runs (stage models)", () => {
    it("switches to the measure model for the kickoff baseline", () => {
      service.startRun(splitConfig);

      expect(modelSwitches).toEqual([
        { taskId: TASK_ID, model: "claude-haiku-4-5" },
      ]);
    });

    it("alternates implement and measure turns with model switches", async () => {
      service.startRun(splitConfig);
      modelSwitches = [];

      // Baseline report -> implement phase on the implement model. The model
      // switch is awaited before the send, so flush the microtask queue.
      runTurn(reportText(10, "baseline"));
      await flush();
      expect(activeRun().phase).toBe("implement");
      expect(modelSwitches).toEqual([
        { taskId: TASK_ID, model: "claude-opus-4-8" },
      ]);
      expect(sentPrompts.at(-1)?.prompt).toContain("Implementation phase");
      expect(sentPrompts.at(-1)?.prompt).toContain(
        "Do NOT run the measurement",
      );

      // Implement turn ends without a report -> measure phase, cheap model,
      // and no missing-report reminder.
      runTurn("Refactored the hot path.");
      await passReminderGrace();
      expect(activeRun().phase).toBe("measure");
      expect(modelSwitches.at(-1)).toEqual({
        taskId: TASK_ID,
        model: "claude-haiku-4-5",
      });
      expect(sentPrompts.at(-1)?.prompt).toContain("Measurement phase");
      expect(
        sentPrompts.some((p) => p.prompt.includes("did not include")),
      ).toBe(false);

      // Measure turn reports -> iteration recorded, next implement begins.
      runTurn(reportText(12));
      expect(activeRun().iterations).toHaveLength(2);
      expect(activeRun().phase).toBe("implement");
    });

    it("records an opportunistic report from an implement turn", async () => {
      service.startRun(splitConfig);
      runTurn(reportText(10, "baseline"));
      await flush();
      expect(activeRun().phase).toBe("implement");

      // The agent measured during the implement turn anyway; skip the
      // dedicated measure turn and start the next iteration.
      runTurn(reportText(11, "changed and measured"));
      await flush();

      expect(activeRun().iterations).toHaveLength(2);
      expect(activeRun().phase).toBe("implement");
      expect(sentPrompts.at(-1)?.prompt).toContain("Implementation phase");
    });

    it("still fails a measure turn that never reports", async () => {
      service.startRun(splitConfig);
      runTurn(reportText(10, "baseline"));
      runTurn("changed things");
      await passReminderGrace();
      expect(activeRun().phase).toBe("measure");

      runTurn("ran it, forgot the block");
      await passReminderGrace();
      runTurn("still prose");
      await passReminderGrace();

      expect(activeRun().status).toBe("failed");
      expect(activeRun().endReason).toBe("missing-report");
    });

    it("hands the session back on the implement model when the run ends", () => {
      service.startRun(splitConfig);
      runTurn(reportText(10, "baseline"));
      runTurn("changed things");
      modelSwitches = [];

      service.stopRun(activeRun().id);

      expect(modelSwitches).toEqual([
        { taskId: TASK_ID, model: "claude-opus-4-8" },
      ]);
    });

    it("re-applies the phase model when resuming after an interruption", async () => {
      service.startRun(splitConfig);
      runTurn(reportText(10, "baseline"));
      runTurn("changed things");
      await passReminderGrace();
      expect(activeRun().phase).toBe("measure");

      sessionStoreSetters.updateSession(TASK_RUN_ID, { status: "error" });
      expect(activeRun().status).toBe("interrupted");
      modelSwitches = [];
      sentPrompts = [];

      sessionStoreSetters.updateSession(TASK_RUN_ID, { status: "connected" });
      await flush();

      expect(activeRun().status).toBe("running");
      expect(modelSwitches).toEqual([
        { taskId: TASK_ID, model: "claude-haiku-4-5" },
      ]);
      expect(sentPrompts.at(-1)?.prompt).toContain("resuming now");
      expect(sentPrompts.at(-1)?.prompt).toContain("Measurement phase");
    });
  });

  describe("rate limits", () => {
    it("interrupts instead of failing when a send is rate-limited", async () => {
      sendPromptImpl = () => Promise.resolve({ stopReason: "rate_limited" });
      const run = service.startRun(baseConfig);
      await flush();

      const stored = autoresearchStore.getState().runs[run.id];
      expect(stored?.status).toBe("interrupted");
      expect(stored?.interruptedReason).toBe("rate-limited");
    });

    it("does not burn a reminder on a rate-limited send", async () => {
      service.startRun(baseConfig);
      runTurn(reportText(10));
      expect(activeRun().iterations).toHaveLength(1);

      // The continuation for iteration 2 gets rate-limited. The send echoes
      // a session/prompt request but the agent produces no reply text, so
      // without the grace period this would look like a missing report.
      sendPromptImpl = () => Promise.resolve({ stopReason: "rate_limited" });
      runTurn(reportText(11));
      beginTurn();
      sessionStoreSetters.updateSession(TASK_RUN_ID, {
        isPromptPending: false,
      });
      await passReminderGrace();

      const run = activeRun();
      expect(run.status).toBe("interrupted");
      expect(run.interruptedReason).toBe("rate-limited");
      expect(run.iterations).toHaveLength(2);
      expect(
        sentPrompts.some((p) => p.prompt.includes("did not include")),
      ).toBe(false);
    });

    it("retries after the recovery delay and resumes when the limit clears", async () => {
      sendPromptImpl = () => Promise.resolve({ stopReason: "rate_limited" });
      const run = service.startRun(baseConfig);
      await flush();
      expect(autoresearchStore.getState().runs[run.id]?.status).toBe(
        "interrupted",
      );

      sendPromptImpl = () => Promise.resolve({ stopReason: "end_turn" });
      await passRecoveryDelay();

      const stored = autoresearchStore.getState().runs[run.id];
      expect(stored?.status).toBe("running");
      expect(stored?.interruptedReason).toBeNull();
      expect(sentPrompts.at(-1)?.prompt).toContain("resuming now");
    });
  });

  describe("session errors and recovery", () => {
    it("interrupts the run when the session errors out", () => {
      service.startRun(baseConfig);
      sessionStoreSetters.updateSession(TASK_RUN_ID, {
        status: "error",
        errorMessage: "agent crashed",
      });

      const run = activeRun();
      expect(run.status).toBe("interrupted");
      expect(run.interruptedReason).toBe("session-error");
      expect(run.lastError).toBe("agent crashed");
    });

    it("resumes automatically when the session reconnects", async () => {
      service.startRun(baseConfig);
      runTurn(reportText(10));
      sessionStoreSetters.updateSession(TASK_RUN_ID, {
        status: "error",
        errorMessage: "idle killed",
      });
      expect(activeRun().status).toBe("interrupted");
      sentPrompts = [];

      sessionStoreSetters.updateSession(TASK_RUN_ID, {
        status: "connected",
        errorMessage: undefined,
      });

      expect(activeRun().status).toBe("running");
      expect(sentPrompts).toHaveLength(1);
      expect(sentPrompts[0].prompt).toContain("resuming now");
      expect(sentPrompts[0].prompt).toContain("iteration 2");
    });

    it("asks the host to reconnect a dead session on the recovery tick", async () => {
      service.startRun(baseConfig);
      sessionStoreSetters.updateSession(TASK_RUN_ID, { status: "error" });
      expect(activeRun().status).toBe("interrupted");

      await passRecoveryDelay();

      expect(reconnectCalls).toEqual([TASK_ID]);
      // Still interrupted until the session actually comes back.
      expect(activeRun().status).toBe("interrupted");

      sessionStoreSetters.updateSession(TASK_RUN_ID, { status: "connected" });
      expect(activeRun().status).toBe("running");
    });

    it("interrupts the run when a continuation prompt cannot be sent", async () => {
      service.startRun(baseConfig);
      sendPromptImpl = () => Promise.reject(new Error("disconnected"));
      runTurn(reportText(10));
      await flush();

      const run = activeRun();
      expect(run.status).toBe("interrupted");
      expect(run.interruptedReason).toBe("send-failed");
      expect(run.iterations).toHaveLength(1);
    });

    it("pauses the run when the user cancels the turn", async () => {
      sendPromptImpl = () => Promise.resolve({ stopReason: "cancelled" });
      const run = service.startRun(baseConfig);
      await flush();

      expect(autoresearchStore.getState().runs[run.id]?.status).toBe("paused");
    });
  });

  describe("pause and resume", () => {
    it("records and settles paused duration", () => {
      vi.setSystemTime(1_000);
      const run = service.startRun(baseConfig);

      vi.setSystemTime(11_000);
      service.pauseRun(run.id);
      expect(activeRun().pausedAt).toBe(11_000);
      expect(activeRun().pausedDurationMs).toBe(0);

      vi.setSystemTime(31_000);
      service.resumeRun(run.id);
      expect(activeRun().pausedAt).toBeNull();
      expect(activeRun().pausedDurationMs).toBe(20_000);
      expect(activeRun().pauseIntervals).toEqual([
        { startedAt: 11_000, endedAt: 31_000 },
      ]);
    });

    it("excludes interruption downtime and records its interval", async () => {
      vi.setSystemTime(1_000);
      service.startRun(baseConfig);
      await flush();

      vi.setSystemTime(11_000);
      sessionStoreSetters.updateSession(TASK_RUN_ID, { status: "error" });
      expect(activeRun().status).toBe("interrupted");
      expect(activeRun().pausedAt).toBe(11_000);

      vi.setSystemTime(31_000);
      sessionStoreSetters.updateSession(TASK_RUN_ID, { status: "connected" });
      await flush();

      expect(activeRun().status).toBe("running");
      expect(activeRun().pausedAt).toBeNull();
      expect(activeRun().pausedDurationMs).toBe(20_000);
      expect(activeRun().pauseIntervals).toEqual([
        { startedAt: 11_000, endedAt: 31_000 },
      ]);
    });

    it("records iterations while paused but does not continue the loop", () => {
      const run = service.startRun(baseConfig);
      service.pauseRun(run.id);
      runTurn(reportText(10));

      expect(activeRun().status).toBe("paused");
      expect(activeRun().iterations).toHaveLength(1);
      expect(sentPrompts).toHaveLength(1);
    });

    it("does not nag about missing reports while paused", async () => {
      const run = service.startRun(baseConfig);
      service.pauseRun(run.id);
      runTurn("just chatting");
      await passReminderGrace();

      expect(sentPrompts).toHaveLength(1);
      expect(activeRun().status).toBe("paused");
    });

    it("a user pause outranks interruptions and auto-resume", async () => {
      const run = service.startRun(baseConfig);
      service.pauseRun(run.id);

      sessionStoreSetters.updateSession(TASK_RUN_ID, { status: "error" });
      expect(activeRun().status).toBe("paused");

      sessionStoreSetters.updateSession(TASK_RUN_ID, { status: "connected" });
      await passRecoveryDelay();
      expect(activeRun().status).toBe("paused");
      expect(reconnectCalls).toHaveLength(0);
      expect(sentPrompts).toHaveLength(1);
    });

    it("resume sends a continuation when the agent is idle", () => {
      const run = service.startRun(baseConfig);
      runTurn(reportText(10));
      service.pauseRun(run.id);
      sentPrompts = [];

      service.resumeRun(run.id);

      expect(activeRun().status).toBe("running");
      expect(sentPrompts).toHaveLength(1);
      expect(sentPrompts[0].prompt).toContain("iteration 2");
    });

    it("resume waits for the agent when a turn is in flight", () => {
      vi.setSystemTime(1_000);
      const run = service.startRun(baseConfig);

      vi.setSystemTime(11_000);
      service.pauseRun(run.id);
      beginTurn();
      sentPrompts = [];

      vi.setSystemTime(31_000);
      service.resumeRun(run.id);
      expect(sentPrompts).toHaveLength(0);
      expect(activeRun().pausedAt).toBeNull();
      expect(activeRun().pausedDurationMs).toBe(20_000);
      expect(activeRun().pauseIntervals).toEqual([
        { startedAt: 11_000, endedAt: 31_000 },
      ]);

      completeTurn(reportText(10));
      expect(activeRun().iterations).toHaveLength(1);
      expect(sentPrompts).toHaveLength(1);
    });

    it("resume completes the run when it already met its end condition", () => {
      const run = service.startRun({ ...baseConfig, maxIterations: 1 });
      service.pauseRun(run.id);
      runTurn(reportText(10));

      service.resumeRun(run.id);

      expect(activeRun().status).toBe("completed");
      expect(activeRun().endReason).toBe("max-iterations");
      expect(sentPrompts).toHaveLength(1);
    });

    it("resume with a dead session goes through recovery instead of sending", () => {
      const run = service.startRun(baseConfig);
      service.pauseRun(run.id);
      sessionStoreSetters.updateSession(TASK_RUN_ID, { status: "error" });
      sentPrompts = [];

      service.resumeRun(run.id);

      expect(activeRun().status).toBe("interrupted");
      expect(sentPrompts).toHaveLength(0);
      expect(reconnectCalls).toEqual([TASK_ID]);
    });

    it("pause applies to interrupted runs and stops recovery", async () => {
      service.startRun(baseConfig);
      sessionStoreSetters.updateSession(TASK_RUN_ID, { status: "error" });
      const run = activeRun();
      expect(run.status).toBe("interrupted");

      service.pauseRun(run.id);
      expect(activeRun().status).toBe("paused");

      await passRecoveryDelay();
      expect(reconnectCalls).toHaveLength(0);
    });

    it("pause does not apply to ended runs", () => {
      const run = service.startRun(baseConfig);
      service.stopRun(run.id);
      service.pauseRun(run.id);
      expect(activeRun().status).toBe("stopped");
    });
  });

  describe("stop", () => {
    it("stopRun marks the run stopped and ends the loop", () => {
      const run = service.startRun(baseConfig);
      service.stopRun(run.id);
      runTurn(reportText(10));

      const stored = activeRun();
      expect(stored.status).toBe("stopped");
      expect(stored.endReason).toBe("stopped-by-user");
      expect(stored.iterations).toHaveLength(0);
      expect(sentPrompts).toHaveLength(1);
    });

    it("stopRun ends an interrupted run without further recovery", async () => {
      service.startRun(baseConfig);
      sessionStoreSetters.updateSession(TASK_RUN_ID, { status: "error" });
      const run = activeRun();
      expect(run.status).toBe("interrupted");

      service.stopRun(run.id);
      await passRecoveryDelay();

      expect(activeRun().status).toBe("stopped");
      expect(reconnectCalls).toHaveLength(0);
    });

    it("a late send failure does not overwrite an already-ended run", async () => {
      sendPromptImpl = () => Promise.reject(new Error("disconnected"));
      const run = service.startRun(baseConfig);
      // The user stops the run while the kickoff send is still in flight.
      service.stopRun(run.id);
      await flush();

      const stored = activeRun();
      expect(stored.status).toBe("stopped");
      expect(stored.endReason).toBe("stopped-by-user");
    });
  });

  describe("persistence", () => {
    it("persists on register, iteration, and terminal transitions", async () => {
      const run = service.startRun(baseConfig);
      await flush();
      expect(savedRuns.length).toBeGreaterThanOrEqual(1);
      expect(savedRuns[0]).toMatchObject({
        id: run.id,
        taskId: TASK_ID,
        endedAt: null,
      });

      runTurn(reportText(10));
      await flush();
      expect(savedRuns.length).toBeGreaterThanOrEqual(2);

      service.stopRun(run.id);
      await flush();
      const last = savedRuns.at(-1);
      expect(last?.endedAt).not.toBeNull();
      expect(JSON.parse(last?.data ?? "{}")).toMatchObject({
        id: run.id,
        status: "stopped",
      });
    });

    it("keeps the loop alive when persistence fails", async () => {
      storageClient.save.mockImplementation(() =>
        Promise.reject(new Error("db locked")),
      );
      service.startRun(baseConfig);
      runTurn(reportText(10));
      await flush();

      expect(activeRun().status).toBe("running");
      expect(activeRun().iterations).toHaveLength(1);
    });
  });

  describe("rehydrate", () => {
    it("restores open runs; running ones come back interrupted", async () => {
      const wasRunning = makeRun({
        id: "ar-stored-running",
        config: { taskId: "task-9" },
        iterations: [
          {
            index: 1,
            value: 10,
            bestValue: 10,
            delta: null,
            summary: "baseline",
            hypothesis: null,
            plan: null,
            approach: null,
            at: 1_000,
          },
        ],
      });
      const wasPaused = makeRun({
        id: "ar-stored-paused",
        status: "paused",
        config: { taskId: "task-10" },
      });
      listOpenImpl = () =>
        Promise.resolve([
          storedRow(wasRunning),
          storedRow(wasPaused),
          { id: "bad", taskId: "task-11", endedAt: null, data: "{corrupt" },
        ]);

      await service.rehydrate();

      const state = autoresearchStore.getState();
      expect(state.runs["ar-stored-running"]).toMatchObject({
        status: "interrupted",
        interruptedReason: "app-restart",
      });
      expect(state.runs["ar-stored-running"]?.iterations).toHaveLength(1);
      expect(state.runs["ar-stored-paused"]?.status).toBe("paused");
      expect(state.runs.bad).toBeUndefined();
      expect(state.activeRunIdByTask["task-9"]).toBe("ar-stored-running");
    });

    it("schedules recovery for restored interrupted runs", async () => {
      listOpenImpl = () =>
        Promise.resolve([
          storedRow(makeRun({ id: "ar-r", config: { taskId: "task-9" } })),
        ]);
      await service.rehydrate();

      // No session exists for task 9 yet. Recovery asks the host to
      // reconnect it.
      await passRecoveryDelay();
      expect(reconnectCalls).toEqual(["task-9"]);
    });

    it("only rehydrates once", async () => {
      await service.rehydrate();
      await service.rehydrate();
      expect(storageClient.listOpen).toHaveBeenCalledTimes(1);
    });

    it("stays dormant when the feature flag is off", async () => {
      gateEnabledImpl = () => Promise.resolve(false);
      listOpenImpl = () =>
        Promise.resolve([
          storedRow(makeRun({ id: "ar-r", config: { taskId: "task-9" } })),
        ]);

      await service.rehydrate();

      expect(storageClient.listOpen).not.toHaveBeenCalled();
      expect(autoresearchStore.getState().runs["ar-r"]).toBeUndefined();
      await passRecoveryDelay();
      expect(reconnectCalls).toHaveLength(0);
    });
  });

  describe("hydrateTask", () => {
    it("loads a task's history without clobbering in-memory runs", async () => {
      const live = service.startRun(baseConfig);
      runTurn(reportText(10));

      const staleLive = makeRun({ id: live.id, iterations: [] });
      const past = makeRun({
        id: "ar-past",
        status: "completed",
        endedAt: 500,
        endReason: "target-reached",
        startedAt: 1,
      });
      listByTaskImpl = () =>
        Promise.resolve([storedRow(past), storedRow(staleLive)]);

      await service.hydrateTask(TASK_ID);

      const state = autoresearchStore.getState();
      // The in-memory run (with its recorded iteration) wins over the row.
      expect(state.runs[live.id]?.iterations).toHaveLength(1);
      expect(state.runs["ar-past"]?.status).toBe("completed");
      // The live run stays active because it started later.
      expect(state.activeRunIdByTask[TASK_ID]).toBe(live.id);
    });

    it("queries storage once per task", async () => {
      await service.hydrateTask(TASK_ID);
      await service.hydrateTask(TASK_ID);
      expect(storageClient.listByTask).toHaveBeenCalledTimes(1);
    });
  });

  describe("interruption and cancel edges", () => {
    it("defers the measure phase so a pause during the grace window wins", async () => {
      service.startRun(splitConfig);
      await flush();
      runTurn(reportText(10, "baseline"));
      await flush();
      expect(activeRun().phase).toBe("implement");
      sentPrompts = [];

      // The implement turn ends without a report, arming the deferred advance
      // to the measure phase. Before the grace elapses the run is paused (as a
      // cancelled implement send would do).
      runTurn("Made the change.");
      service.pauseRun(activeRun().id);
      await passReminderGrace();

      // No measure prompt was sent to the agent the user just silenced.
      expect(activeRun().status).toBe("paused");
      expect(activeRun().phase).toBe("implement");
      expect(
        sentPrompts.some((p) => p.prompt.includes("Measurement phase")),
      ).toBe(false);
    });

    it("gives a recovered run a fresh reminder budget", async () => {
      service.startRun(baseConfig);
      await flush();

      runTurn("no report");
      await passReminderGrace();
      expect(sentPrompts.at(-1)?.prompt).toContain("did not include");

      // The session drops after the first missed report, then recovers.
      sessionStoreSetters.updateSession(TASK_RUN_ID, { status: "error" });
      expect(activeRun().status).toBe("interrupted");
      sessionStoreSetters.updateSession(TASK_RUN_ID, { status: "connected" });
      await flush();
      expect(activeRun().status).toBe("running");

      // The first reportless turn after recovery reminds again instead of
      // failing on a stale pre-interruption reminder count.
      runTurn("still no report");
      await passReminderGrace();
      expect(activeRun().status).toBe("running");
      expect(activeRun().endReason).toBeNull();
      expect(sentPrompts.at(-1)?.prompt).toContain("did not include");
    });

    it("keeps the loop running when a send is queued behind a busy session", async () => {
      service.startRun(baseConfig);
      await flush();

      sendPromptImpl = () => Promise.resolve({ stopReason: "queued" });
      runTurn(reportText(10));
      await flush();

      // The iteration was still recorded; the queued continuation drains later.
      expect(activeRun().iterations).toHaveLength(1);
      expect(activeRun().status).toBe("running");
      expect(activeRun().interruptedReason).toBeNull();
    });

    it("does not spend the automatic-recovery budget on a manual resume", () => {
      service.startRun(baseConfig);
      sessionStoreSetters.updateSession(TASK_RUN_ID, { status: "error" });
      const runId = activeRun().id;
      expect(activeRun().status).toBe("interrupted");

      // Pretend automatic recovery has nearly given up.
      const attempts = (
        service as unknown as { recoveryAttempts: Map<string, number> }
      ).recoveryAttempts;
      attempts.set(runId, MAX_RECOVERY_ATTEMPTS - 1);

      // A manual resume on the still-down session refreshes the budget before
      // its own attempt, so automatic recovery is not left exhausted.
      service.resumeRun(runId);
      expect(attempts.get(runId) ?? 0).toBeLessThan(MAX_RECOVERY_ATTEMPTS);
    });
  });

  describe("effort-only splits", () => {
    it("alternates efforts between phases without touching the model", async () => {
      service.startRun({
        ...baseConfig,
        implementEffort: "high",
        measureEffort: "low",
      });
      // Kickoff baseline runs on the measure stage's effort.
      expect(effortSwitches).toEqual([{ taskId: TASK_ID, effort: "low" }]);
      await flush();
      effortSwitches = [];

      runTurn(reportText(10, "baseline"));
      await flush();
      expect(activeRun().phase).toBe("implement");
      expect(effortSwitches).toEqual([{ taskId: TASK_ID, effort: "high" }]);
      expect(modelSwitches).toEqual([]);

      runTurn("changed the cache layout");
      await passReminderGrace();
      expect(activeRun().phase).toBe("measure");
      expect(effortSwitches.at(-1)).toEqual({ taskId: TASK_ID, effort: "low" });
      expect(modelSwitches).toEqual([]);
    });

    it("treats identical stages as a single-turn run", () => {
      service.startRun({
        ...baseConfig,
        implementModel: "claude-opus-4-8",
        measureModel: "claude-opus-4-8",
        implementEffort: "high",
        measureEffort: "high",
      });
      runTurn(reportText(10, "baseline"));

      // No phase alternation: the next prompt is a plain continuation.
      expect(activeRun().phase).toBeNull();
      expect(sentPrompts.at(-1)?.prompt).toContain(
        "Then make the next focused change",
      );
    });
  });

  describe("stage-model restoration", () => {
    it("restores the user's model when a split run ends", async () => {
      sessionStoreSetters.setSession(
        makeSession({ configOptions: modelConfig("claude-sonnet-4-6") }),
      );
      const run = service.startRun(splitConfig);
      await flush();
      modelSwitches = [];

      service.stopRun(run.id);
      await flush();

      expect(modelSwitches).toEqual([
        { taskId: TASK_ID, model: "claude-sonnet-4-6" },
      ]);
    });

    it("restores the user's model when a split run is paused", async () => {
      sessionStoreSetters.setSession(
        makeSession({ configOptions: modelConfig("claude-sonnet-4-6") }),
      );
      const run = service.startRun(splitConfig);
      await flush();
      modelSwitches = [];

      service.pauseRun(run.id);
      await flush();

      expect(modelSwitches).toEqual([
        { taskId: TASK_ID, model: "claude-sonnet-4-6" },
      ]);
    });

    it("restores the user's effort alongside the model", async () => {
      sessionStoreSetters.setSession(
        makeSession({
          configOptions: modelConfig("claude-sonnet-4-6", "medium"),
        }),
      );
      const run = service.startRun({
        ...splitConfig,
        implementEffort: "high",
        measureEffort: "low",
      });
      await flush();
      modelSwitches = [];
      effortSwitches = [];

      service.stopRun(run.id);
      await flush();

      expect(modelSwitches).toEqual([
        { taskId: TASK_ID, model: "claude-sonnet-4-6" },
      ]);
      expect(effortSwitches).toEqual([{ taskId: TASK_ID, effort: "medium" }]);
    });
  });
});
