import { beforeEach, describe, expect, it } from "vitest";
import { useMessagingModeStore } from "./messagingModeStore";

const INITIAL_STATE = useMessagingModeStore.getState();

describe("messagingModeStore", () => {
  beforeEach(() => {
    useMessagingModeStore.setState(
      { ...INITIAL_STATE, modesByTaskId: {}, defaultMode: "queue" },
      true,
    );
  });

  it("defaults to Queue", () => {
    expect(useMessagingModeStore.getState().getEffectiveMode("t1")).toBe(
      "queue",
    );
  });

  it("falls back to the global default when a task has no override", () => {
    useMessagingModeStore.getState().setDefaultMode("steer");
    expect(useMessagingModeStore.getState().getEffectiveMode("t1")).toBe(
      "steer",
    );
  });

  it("prefers a per-task override over the global default", () => {
    useMessagingModeStore.getState().setDefaultMode("steer");
    useMessagingModeStore.getState().setMode("t1", "queue");
    expect(useMessagingModeStore.getState().getEffectiveMode("t1")).toBe(
      "queue",
    );
    // A different task still resolves to the global default.
    expect(useMessagingModeStore.getState().getEffectiveMode("t2")).toBe(
      "steer",
    );
  });

  it("treats an undefined taskId as the global default", () => {
    useMessagingModeStore.getState().setDefaultMode("steer");
    expect(useMessagingModeStore.getState().getEffectiveMode(undefined)).toBe(
      "steer",
    );
  });
});
