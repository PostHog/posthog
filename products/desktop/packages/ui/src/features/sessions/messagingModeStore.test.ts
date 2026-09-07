import { beforeEach, describe, expect, it } from "vitest";
import { useMessagingModeStore } from "./messagingModeStore";

describe("messagingModeStore", () => {
  beforeEach(() => {
    useMessagingModeStore.setState({ modesByTaskId: {} });
  });

  it("stores a per-task mode override", () => {
    useMessagingModeStore.getState().setMode("task-1", "steer");
    expect(useMessagingModeStore.getState().modesByTaskId["task-1"]).toBe(
      "steer",
    );
  });

  it("keeps overrides independent per task", () => {
    useMessagingModeStore.getState().setMode("task-1", "steer");
    useMessagingModeStore.getState().setMode("task-2", "queue");
    expect(useMessagingModeStore.getState().modesByTaskId).toEqual({
      "task-1": "steer",
      "task-2": "queue",
    });
  });
});
