import type { BrowserTab, TabsSnapshot } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  displayedTabIds,
  frontOfUnpinnedOrder,
  partitionPinnedFirst,
  reorderWithinGroup,
  storedOrderIds,
} from "./displayOrder";

function tab(id: string, position: number): BrowserTab {
  return {
    id,
    windowId: "w1",
    dashboardId: null,
    taskId: null,
    channelId: null,
    channelSection: null,
    appView: null,
    position,
    scrollState: null,
    createdAt: 0,
    lastActiveAt: 0,
  };
}

/** Snapshot whose stored order (by position) is the given ids. */
function snap(ids: string[]): TabsSnapshot {
  return {
    windows: [{ id: "w1", isPrimary: true, bounds: null, activeTabId: null }],
    tabs: ids.map((id, i) => tab(id, (i + 1) * 1000)),
  };
}

describe("storedOrderIds", () => {
  it("orders a window's tabs by position", () => {
    expect(storedOrderIds(snap(["a", "b", "c"]), "w1")).toEqual([
      "a",
      "b",
      "c",
    ]);
  });
});

describe("partitionPinnedFirst", () => {
  it("moves pinned tabs to the front, keeping each group's order", () => {
    expect(partitionPinnedFirst(["a", "b", "c", "d"], ["c", "b"])).toEqual([
      "b",
      "c",
      "a",
      "d",
    ]);
  });

  it("is a no-op when nothing is pinned", () => {
    expect(partitionPinnedFirst(["a", "b"], [])).toEqual(["a", "b"]);
  });
});

describe("displayedTabIds", () => {
  it("is stored order with the pinned-first partition applied", () => {
    expect(displayedTabIds(snap(["a", "b", "c", "p"]), "w1", ["p"])).toEqual([
      "p",
      "a",
      "b",
      "c",
    ]);
  });
});

describe("reorderWithinGroup", () => {
  it("moves an unpinned tab without disturbing pinned stored positions", () => {
    // stored [a, b, c, p] with p pinned; move b after c.
    const next = reorderWithinGroup(["a", "b", "c", "p"], ["p"], "b", "c");
    expect(next).toEqual(["a", "c", "b", "p"]);
    // p keeps its stored slot (last), so its display-first position never leaks
    // into stored order.
    expect(next.indexOf("p")).toBe(3);
  });

  it("keeps the other group's tabs in their exact stored slots", () => {
    // stored [a, p, b, c] (p pinned at index 1); move a to c.
    const next = reorderWithinGroup(["a", "p", "b", "c"], ["p"], "a", "c");
    expect(next).toEqual(["b", "p", "c", "a"]);
    expect(next[1]).toBe("p");
  });

  it("refuses a cross-group move", () => {
    const stored = ["a", "b", "p"];
    expect(reorderWithinGroup(stored, ["p"], "a", "p")).toBe(stored);
  });

  it("is a no-op when source and target are the same", () => {
    const stored = ["a", "b", "c"];
    expect(reorderWithinGroup(stored, [], "b", "b")).toBe(stored);
  });
});

describe("frontOfUnpinnedOrder", () => {
  it("moves the tab just before the first unpinned tab", () => {
    // stored [p, a, b, c] with p still pinned; unpin c → front of unpinned = a.
    const order = frontOfUnpinnedOrder(snap(["p", "a", "b", "c"]), "w1", "c", [
      "p",
    ]);
    expect(order).toEqual(["p", "c", "a", "b"]);
  });

  it("appends when there is no other unpinned tab", () => {
    const order = frontOfUnpinnedOrder(snap(["p", "c"]), "w1", "c", ["p"]);
    expect(order).toEqual(["p", "c"]);
  });
});
