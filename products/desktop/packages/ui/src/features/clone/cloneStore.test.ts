import { cloneStore } from "@posthog/ui/features/clone/cloneStore";
import { beforeEach, describe, expect, it } from "vitest";

const reset = () => cloneStore.setState({ operations: {} });

describe("cloneStore", () => {
  beforeEach(reset);

  it("registers a cloning operation with beginClone", () => {
    cloneStore.getState().beginClone("c1", "owner/repo", "/tmp/repo");

    const op = cloneStore.getState().operations.c1;
    expect(op).toMatchObject({
      cloneId: "c1",
      repository: "owner/repo",
      targetPath: "/tmp/repo",
      status: "cloning",
    });
    expect(op.latestMessage).toContain("owner/repo");
  });

  it("updates status and message from progress events", () => {
    cloneStore.getState().beginClone("c1", "owner/repo", "/tmp/repo");
    cloneStore
      .getState()
      .applyProgress({ cloneId: "c1", status: "cloning", message: "50%" });

    const op = cloneStore.getState().operations.c1;
    expect(op.status).toBe("cloning");
    expect(op.latestMessage).toBe("50%");
  });

  it("records the error message on an error event", () => {
    cloneStore.getState().beginClone("c1", "owner/repo", "/tmp/repo");
    cloneStore
      .getState()
      .applyProgress({ cloneId: "c1", status: "error", message: "boom" });

    const op = cloneStore.getState().operations.c1;
    expect(op.status).toBe("error");
    expect(op.error).toBe("boom");
  });

  it("ignores progress for an unknown cloneId", () => {
    cloneStore
      .getState()
      .applyProgress({ cloneId: "ghost", status: "complete", message: "done" });

    expect(cloneStore.getState().operations.ghost).toBeUndefined();
  });

  it("removes an operation with removeClone", () => {
    cloneStore.getState().beginClone("c1", "owner/repo", "/tmp/repo");
    cloneStore.getState().removeClone("c1");

    expect(cloneStore.getState().operations.c1).toBeUndefined();
  });
});
