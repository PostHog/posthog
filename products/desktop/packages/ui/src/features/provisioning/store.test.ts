import { beforeEach, describe, expect, it } from "vitest";
import { useProvisioningStore } from "./store";

describe("useProvisioningStore", () => {
  beforeEach(() => {
    useProvisioningStore.setState({
      activeTasks: new Set(),
      output: {},
      errors: {},
    });
  });

  it("records a provisioning failure and stops treating the task as active", () => {
    const { setActive, setFailed } = useProvisioningStore.getState();
    setActive("task-1");
    setFailed("task-1", "worktree boom");

    const state = useProvisioningStore.getState();
    expect(state.errors["task-1"]).toBe("worktree boom");
    expect(state.activeTasks.has("task-1")).toBe(false);
  });

  it("clears a stale error when the task provisions again", () => {
    const { setFailed, setActive } = useProvisioningStore.getState();
    setFailed("task-1", "worktree boom");
    setActive("task-1");

    expect(useProvisioningStore.getState().errors["task-1"]).toBeUndefined();
  });

  it("clear removes the error alongside active state and output", () => {
    const { setFailed, appendChunk, clear } = useProvisioningStore.getState();
    setFailed("task-1", "worktree boom");
    appendChunk("task-1", "line");
    clear("task-1");

    const state = useProvisioningStore.getState();
    expect(state.errors["task-1"]).toBeUndefined();
    expect(state.output["task-1"]).toBeUndefined();
  });
});
