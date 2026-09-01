import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useMessagingModeStore } from "../messagingModeStore";
import {
  type AgentSession,
  sessionStoreSetters,
  useSessionStore,
} from "../sessionStore";
import { useMessagingMode } from "./useMessagingMode";

function seedSession(overrides: Partial<AgentSession>): void {
  sessionStoreSetters.setSession({
    taskRunId: "run-1",
    taskId: "task-1",
    taskTitle: "Test",
    channel: "agent-event:run-1",
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
  });
}

describe("useMessagingMode", () => {
  beforeEach(() => {
    useMessagingModeStore.setState({ modesByTaskId: {} });
    useSettingsStore.setState({
      defaultMessagingMode: "queue",
      defaultCloudMessagingMode: "steer",
    });
    useSessionStore.setState((state) => {
      state.sessions = {};
      state.taskIdIndex = {};
    });
  });

  it("per-task override wins over any default", () => {
    seedSession({ isCloud: true });
    useMessagingModeStore.getState().setMode("task-1", "queue");
    const { result } = renderHook(() => useMessagingMode("task-1"));
    expect(result.current).toBe("queue");
  });

  it("returns global cloud default for cloud sessions", () => {
    seedSession({ isCloud: true });
    const { result } = renderHook(() => useMessagingMode("task-1"));
    expect(result.current).toBe("steer");
  });

  it("returns global local default for local sessions", () => {
    seedSession({ isCloud: false });
    const { result } = renderHook(() => useMessagingMode("task-1"));
    expect(result.current).toBe("queue");
  });

  it("returns global local default when no session exists for the task", () => {
    const { result } = renderHook(() => useMessagingMode("task-1"));
    expect(result.current).toBe("queue");
  });

  it("returns global local default when taskId is undefined", () => {
    seedSession({ isCloud: true });
    const { result } = renderHook(() => useMessagingMode(undefined));
    expect(result.current).toBe("queue");
  });

  it("respects a changed cloud messaging mode default", () => {
    seedSession({ isCloud: true });
    useSettingsStore.getState().setDefaultCloudMessagingMode("queue");
    const { result } = renderHook(() => useMessagingMode("task-1"));
    expect(result.current).toBe("queue");
  });
});
