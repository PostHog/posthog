import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  type CanvasFrameInputs,
  useCanvasFrameStore,
} from "./canvasFrameStore";

function inputs(code: string): CanvasFrameInputs {
  return { code, onDataRequest: vi.fn() };
}

function reset() {
  useCanvasFrameStore.setState({
    slots: [],
    activeDashboardId: null,
    maxWarmFrames: 2,
    frameKeys: {},
  });
}

function slotIndexOf(dashboardId: string): number {
  return useCanvasFrameStore
    .getState()
    .slots.findIndex((s) => s?.dashboardId === dashboardId);
}

describe("canvasFrameStore", () => {
  beforeEach(reset);

  it("assigns each new canvas to its own free slot until the pool is full", () => {
    const { register } = useCanvasFrameStore.getState();
    register("a", inputs("A"));
    register("b", inputs("B"));

    const { slots } = useCanvasFrameStore.getState();
    expect(slots.filter(Boolean)).toHaveLength(2);
    expect(slotIndexOf("a")).toBe(0);
    expect(slotIndexOf("b")).toBe(1);
  });

  it("re-registering an existing canvas updates inputs in place (no new slot)", () => {
    const { register } = useCanvasFrameStore.getState();
    register("a", inputs("A"));
    register("a", inputs("A2"));

    const { slots } = useCanvasFrameStore.getState();
    expect(slots.filter(Boolean)).toHaveLength(1);
    expect(slots[0]?.inputs.code).toBe("A2");
  });

  // Each op is "reg:<id>" (register) or "act:<id>" (activate); `expected` maps a
  // canvas id to its final slot index (-1 = evicted). The pool size is 2.
  it.each([
    {
      name: "reuses the least-recently-active slot when the pool is full",
      ops: ["reg:a", "act:a", "reg:b", "act:b", "reg:c"],
      expected: { a: -1, b: 1, c: 0 },
    },
    {
      name: "never evicts the active canvas, even if it is the oldest activated",
      ops: ["reg:a", "act:a", "reg:b", "act:b", "act:a", "reg:c"],
      expected: { a: 0, b: -1, c: 1 },
    },
    {
      name: "re-activating keeps a canvas off the eviction block",
      ops: ["reg:a", "act:a", "reg:b", "act:b", "act:a", "act:b", "reg:c"],
      expected: { a: -1, b: 1, c: 0 },
    },
  ])("$name", ({ ops, expected }) => {
    const { register, activate } = useCanvasFrameStore.getState();
    for (const op of ops) {
      const [kind, id] = op.split(":");
      if (kind === "reg") register(id, inputs(id.toUpperCase()));
      else activate(id);
    }
    for (const [id, slot] of Object.entries(expected)) {
      expect(slotIndexOf(id)).toBe(slot);
    }
    expect(useCanvasFrameStore.getState().slots.filter(Boolean)).toHaveLength(
      2,
    );
  });

  it("setRect skips no-op writes (no new slots array)", () => {
    const { register, setRect } = useCanvasFrameStore.getState();
    register("a", inputs("A"));
    setRect("a", { top: 1, left: 2, width: 3, height: 4 });
    const after = useCanvasFrameStore.getState().slots;
    setRect("a", { top: 1, left: 2, width: 3, height: 4 });
    expect(useCanvasFrameStore.getState().slots).toBe(after);
  });

  it("remount bumps only the frame generation of the canvas's slot", () => {
    const { register, remount } = useCanvasFrameStore.getState();
    register("a", inputs("A"));
    register("b", inputs("B"));

    remount("a");
    expect(useCanvasFrameStore.getState().frameKeys[0]).toBe(1);
    expect(useCanvasFrameStore.getState().frameKeys[1] ?? 0).toBe(0);
  });

  it("remount is a no-op for a canvas with no slot", () => {
    const { remount } = useCanvasFrameStore.getState();
    const before = useCanvasFrameStore.getState().frameKeys;
    remount("missing");
    expect(useCanvasFrameStore.getState().frameKeys).toBe(before);
  });

  it("keeps a slot's remount generation when it is reassigned (warm reuse)", () => {
    const { register, activate, remount } = useCanvasFrameStore.getState();
    register("a", inputs("A"));
    activate("a");
    remount("a"); // slot 0 generation -> 1
    register("b", inputs("B"));
    activate("b");
    register("c", inputs("C")); // evicts LRU "a", "c" takes slot 0

    expect(slotIndexOf("c")).toBe(0);
    // Reassigning slot 0 to a different canvas must NOT change its key, so the
    // warm iframe is reused (code-swap) rather than remounted on navigation.
    expect(useCanvasFrameStore.getState().frameKeys[0]).toBe(1);
  });

  it("deactivate clears the active id only when it matches", () => {
    const { register, activate, deactivate } = useCanvasFrameStore.getState();
    register("a", inputs("A"));
    activate("a");
    deactivate("b");
    expect(useCanvasFrameStore.getState().activeDashboardId).toBe("a");
    deactivate("a");
    expect(useCanvasFrameStore.getState().activeDashboardId).toBeNull();
  });
});
