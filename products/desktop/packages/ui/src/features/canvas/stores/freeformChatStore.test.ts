import { beforeEach, describe, expect, it } from "vitest";
import { useFreeformChatStore } from "./freeformChatStore";

function reset() {
  useFreeformChatStore.setState({ threads: {}, threadOrder: [] });
}

function browse(threadId: string) {
  useFreeformChatStore.getState().setBrowseVersion(threadId, "v1");
}

describe("freeformChatStore eviction", () => {
  beforeEach(reset);

  it("evicts the least recently used threads beyond the cap", () => {
    for (let i = 0; i < 12; i++) browse(`dashboard:${i}`);
    const { threads, threadOrder } = useFreeformChatStore.getState();
    // Cap is 8: the oldest four are gone, the most recent survive.
    expect(threadOrder).toHaveLength(8);
    expect(threads["dashboard:0"]).toBeUndefined();
    expect(threads["dashboard:11"]).toBeDefined();
  });

  it("never evicts a thread with a mounted view", () => {
    // Mount thread 0, then churn far more than the cap through other threads.
    useFreeformChatStore.getState().setThreadMounted("dashboard:0", true);
    browse("dashboard:0");
    for (let i = 1; i < 12; i++) browse(`dashboard:${i}`);

    const { threads } = useFreeformChatStore.getState();
    expect(threads["dashboard:0"]).toBeDefined();
    expect(threads["dashboard:0"].browseVersionId).toBe("v1");
  });

  it("stops protecting a thread once its view unmounts", () => {
    useFreeformChatStore.getState().setThreadMounted("dashboard:0", true);
    browse("dashboard:0");
    useFreeformChatStore.getState().setThreadMounted("dashboard:0", false);
    for (let i = 1; i < 12; i++) browse(`dashboard:${i}`);

    expect(
      useFreeformChatStore.getState().threads["dashboard:0"],
    ).toBeUndefined();
  });
});
