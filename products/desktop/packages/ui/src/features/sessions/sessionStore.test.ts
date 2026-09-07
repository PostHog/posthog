import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { beforeEach, describe, expect, it } from "vitest";
import {
  cycleModeOption,
  sessionStoreSetters,
  useSessionStore,
} from "./sessionStore";

function createModeOption(
  currentValue: string,
  values: string[],
): SessionConfigOption {
  return {
    id: "mode",
    name: "Approval Preset",
    type: "select",
    category: "mode",
    currentValue,
    options: values.map((value) => ({
      value,
      name: value,
    })),
  } as SessionConfigOption;
}

const CLAUDE_MODES = ["default", "acceptEdits", "plan", "bypassPermissions"];
const CODEX_MODES = ["read-only", "auto", "full-access"];

describe("cycleModeOption", () => {
  it.each([
    {
      name: "claude: advances to next mode when bypass allowed",
      values: CLAUDE_MODES,
      currentValue: "plan",
      allowBypassPermissions: true,
      expected: "bypassPermissions",
    },
    {
      name: "codex: advances to next mode when bypass allowed",
      values: CODEX_MODES,
      currentValue: "auto",
      allowBypassPermissions: true,
      expected: "full-access",
    },
    {
      name: "claude: skips bypassPermissions when not allowed",
      values: CLAUDE_MODES,
      currentValue: "acceptEdits",
      allowBypassPermissions: false,
      expected: "plan",
    },
    {
      name: "claude: wraps past bypassPermissions back to default",
      values: CLAUDE_MODES,
      currentValue: "plan",
      allowBypassPermissions: false,
      expected: "default",
    },
    {
      name: "codex: skips full-access when not allowed",
      values: CODEX_MODES,
      currentValue: "auto",
      allowBypassPermissions: false,
      expected: "read-only",
    },
  ])("$name", ({ values, currentValue, allowBypassPermissions, expected }) => {
    const option = createModeOption(currentValue, values);

    expect(cycleModeOption(option, { allowBypassPermissions })).toBe(expected);
  });
});

describe("dequeueMessages", () => {
  beforeEach(() => {
    useSessionStore.setState((state) => {
      state.sessions = {};
      state.taskIdIndex = {};
    });
  });

  it("returns plain objects that survive after the immer setState exits", () => {
    sessionStoreSetters.setSession({
      taskRunId: "run-123",
      taskId: "task-123",
      taskTitle: "Test",
      channel: "agent-event:run-123",
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
    });
    sessionStoreSetters.enqueueMessage("task-123", "first", [
      { type: "text", text: "first" },
    ]);
    sessionStoreSetters.enqueueMessage("task-123", "second", [
      { type: "text", text: "second" },
    ]);

    const drained = sessionStoreSetters.dequeueMessages("task-123");

    // Reading members of drained items must NOT throw "Cannot perform 'get'
    // on a proxy that has been revoked" — the silent root cause behind the
    // cloud-queue dispatcher losing messages. Items returned must be plain
    // objects, not immer drafts that get revoked when setState exits.
    expect(() => drained.map((m) => m.content)).not.toThrow();
    expect(drained.map((m) => m.content)).toEqual(["first", "second"]);
    expect(useSessionStore.getState().sessions["run-123"].messageQueue).toEqual(
      [],
    );
  });
});

describe("updateCloudStatus", () => {
  beforeEach(() => {
    useSessionStore.setState((state) => {
      state.sessions = {};
      state.taskIdIndex = {};
    });
  });

  it("does not downgrade a terminal run when a stale non-terminal status arrives", () => {
    sessionStoreSetters.setSession({
      taskRunId: "run-123",
      taskId: "task-123",
      taskTitle: "Test",
      channel: "agent-event:run-123",
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
      cloudStatus: "completed",
    });

    sessionStoreSetters.updateCloudStatus("run-123", {
      status: "in_progress",
      branch: "stale-branch",
    });

    expect(useSessionStore.getState().sessions["run-123"].cloudStatus).toBe(
      "completed",
    );
    expect(useSessionStore.getState().sessions["run-123"].cloudBranch).toBe(
      undefined,
    );
  });
});

describe("dequeueMessagesAsText", () => {
  beforeEach(() => {
    useSessionStore.setState((state) => {
      state.sessions = {};
      state.taskIdIndex = {};
    });
  });

  it("returns the joined queue text and clears the queue", () => {
    sessionStoreSetters.setSession({
      taskRunId: "run-123",
      taskId: "task-123",
      taskTitle: "Test",
      channel: "agent-event:run-123",
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
    });
    sessionStoreSetters.enqueueMessage("task-123", "first", [
      { type: "text", text: "first" },
    ]);
    sessionStoreSetters.enqueueMessage("task-123", "second", [
      { type: "text", text: "second" },
    ]);

    const combined = sessionStoreSetters.dequeueMessagesAsText("task-123");

    expect(combined).toBe("first\n\nsecond");
    expect(useSessionStore.getState().sessions["run-123"].messageQueue).toEqual(
      [],
    );
  });

  it("returns null for an empty queue", () => {
    sessionStoreSetters.setSession({
      taskRunId: "run-123",
      taskId: "task-123",
      taskTitle: "Test",
      channel: "agent-event:run-123",
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
    });

    expect(sessionStoreSetters.dequeueMessagesAsText("task-123")).toBeNull();
  });

  it("returns null for an unknown task id", () => {
    expect(sessionStoreSetters.dequeueMessagesAsText("nope")).toBeNull();
  });
});

describe("prependQueuedMessages", () => {
  beforeEach(() => {
    useSessionStore.setState((state) => {
      state.sessions = {};
      state.taskIdIndex = {};
    });
  });

  it("splices messages back at the head of the queue", () => {
    sessionStoreSetters.setSession({
      taskRunId: "run-123",
      taskId: "task-123",
      taskTitle: "Test",
      channel: "agent-event:run-123",
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
    });
    sessionStoreSetters.enqueueMessage("task-123", "live", [
      { type: "text", text: "live" },
    ]);

    sessionStoreSetters.prependQueuedMessages("task-123", [
      {
        id: "rolled-back",
        content: "rolled-back",
        rawPrompt: [{ type: "text", text: "rolled-back" }],
        queuedAt: 0,
      },
    ]);

    const queue = useSessionStore.getState().sessions["run-123"].messageQueue;
    expect(queue.map((m) => m.content)).toEqual(["rolled-back", "live"]);
  });
});
