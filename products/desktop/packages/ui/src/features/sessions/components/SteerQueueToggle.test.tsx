import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useSupportsNativeSteer } from "../hooks/useMessagingMode";
import {
  type AgentSession,
  sessionStoreSetters,
  useSessionStore,
} from "../sessionStore";
import { steerQueueTooltip } from "./SteerQueueToggle";

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

describe("steer tooltip copy follows the session's native-steer capability", () => {
  beforeEach(() => {
    useSessionStore.setState((state) => {
      state.sessions = {};
      state.taskIdIndex = {};
    });
  });

  it.each([
    {
      name: "codex (local): interrupts and resends",
      session: { adapter: "codex" as const, isCloud: false },
      expectNative: false,
    },
    {
      name: "claude cloud: interrupts and resends",
      session: { adapter: "claude" as const, isCloud: true },
      expectNative: false,
    },
    {
      name: "claude (local): folds natively at the next tool boundary",
      session: { adapter: "claude" as const, isCloud: false },
      expectNative: true,
    },
  ])(
    "$name — supportsNativeSteer and rendered tooltip agree",
    ({ session, expectNative }) => {
      seedSession(session);

      const { result } = renderHook(() => useSupportsNativeSteer("task-1"));
      expect(result.current).toBe(expectNative);

      const tooltip = steerQueueTooltip(true, result.current, "Cmd+S");
      if (expectNative) {
        expect(tooltip).toContain(
          "injects your message mid-turn at the next tool boundary",
        );
      } else {
        expect(tooltip).toContain(
          "interrupts the current turn and resends with your message",
        );
      }
    },
  );
});
