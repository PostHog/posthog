import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  pendingPromptRecoveryStoreApi,
  usePendingPromptRecoveryStore,
} from "./pendingPromptRecoveryStore";

describe("pendingPromptRecoveryStore", () => {
  beforeEach(() => {
    usePendingPromptRecoveryStore.setState({ byKey: {}, hasHydrated: true });
  });

  it("persists a prompt on submit and clears it on success", () => {
    pendingPromptRecoveryStoreApi.set("pending-1", "Fix the login bug");
    expect(pendingPromptRecoveryStoreApi.getAllNewestFirst()).toEqual([
      {
        key: "pending-1",
        prompt: expect.objectContaining({ promptText: "Fix the login bug" }),
      },
    ]);

    pendingPromptRecoveryStoreApi.clear("pending-1");
    expect(pendingPromptRecoveryStoreApi.getAllNewestFirst()).toEqual([]);
  });

  it("caps the persisted set to the newest 20 entries", () => {
    let now = 1000;
    const spy = vi.spyOn(Date, "now").mockImplementation(() => now++);
    for (let i = 0; i < 25; i++) {
      pendingPromptRecoveryStoreApi.set(`k-${i}`, `prompt ${i}`);
    }
    spy.mockRestore();

    const entries = pendingPromptRecoveryStoreApi.getAllNewestFirst();
    const keys = entries.map((e) => e.key);
    expect(entries).toHaveLength(20);
    expect(keys[0]).toBe("k-24");
    expect(keys).not.toContain("k-0");
    expect(keys).not.toContain("k-4");
  });

  it("orders recoverable prompts newest-first", () => {
    usePendingPromptRecoveryStore.setState({
      byKey: {
        old: { promptText: "old", createdAt: 1 },
        newest: { promptText: "newest", createdAt: 3 },
        mid: { promptText: "mid", createdAt: 2 },
      },
    });

    expect(
      pendingPromptRecoveryStoreApi.getAllNewestFirst().map((e) => e.key),
    ).toEqual(["newest", "mid", "old"]);
  });

  it("whenHydrated resolves once the rehydration flag flips", async () => {
    usePendingPromptRecoveryStore.setState({ hasHydrated: false });
    let resolved = false;
    const pending = pendingPromptRecoveryStoreApi.whenHydrated().then(() => {
      resolved = true;
    });

    expect(resolved).toBe(false);
    usePendingPromptRecoveryStore.getState().setHasHydrated(true);
    await pending;
    expect(resolved).toBe(true);
  });
});
