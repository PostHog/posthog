import { describe, expect, it } from "vitest";
import {
  closeTab,
  closeTabs,
  decideTabNavigation,
  openTab,
  POSITION_GAP,
  primaryWindow,
  resetTabs,
  setTabOrder,
  setTabTarget,
  setWindowActiveTab,
  type TabIdentity,
} from "./browser-tabs";
import type { TabsSnapshot } from "./browser-tabs-schemas";

let idCounter = 0;
const makeId = () => `tab-${++idCounter}`;
let clock = 0;
const now = () => ++clock;

const NO_IDENTITY: TabIdentity = {
  dashboardId: null,
  taskId: null,
  channelId: null,
  channelSection: null,
  appView: null,
};

function snapshot(partial?: Partial<TabsSnapshot>): TabsSnapshot {
  return {
    windows: [{ id: "w1", isPrimary: true, bounds: null, activeTabId: null }],
    tabs: [],
    ...partial,
  };
}

/** Open a canvas tab. The href is the truth; the identity fields are its label cache. */
function open(
  s: TabsSnapshot,
  windowId: string,
  dashboardId: string,
  channelId: string | null = "c1",
) {
  return openTab(s, {
    windowId,
    href: `/spaces/${channelId}/dashboards/${dashboardId}`,
    viewState: null,
    dashboardId,
    taskId: null,
    channelId,
    makeId,
    now,
  });
}

/** Open a tab on a bare href, with no identity to cache. */
function openAt(s: TabsSnapshot, windowId: string, href: string) {
  return openTab(s, {
    windowId,
    href,
    viewState: null,
    ...NO_IDENTITY,
    makeId,
    now,
  });
}

/** A navigation to `href` while `activeTab` is focused. */
function navigate(input: {
  href: string;
  activeTab: {
    id: string;
    href: string | null;
    identity?: TabIdentity;
  } | null;
  historyTabId?: string | null;
  windowTabIds?: string[];
  serverActiveTabId?: string | null;
  identity?: TabIdentity;
}) {
  return decideTabNavigation({
    historyTabId: input.historyTabId ?? null,
    windowTabIds: input.windowTabIds,
    serverActiveTabId:
      input.serverActiveTabId !== undefined
        ? input.serverActiveTabId
        : (input.activeTab?.id ?? null),
    activeTab: input.activeTab
      ? {
          ...input.activeTab,
          viewState: null,
          identity: input.activeTab.identity ?? NO_IDENTITY,
        }
      : null,
    href: input.href,
    viewState: null,
    identity: input.identity ?? NO_IDENTITY,
  });
}

describe("openTab", () => {
  it("opens a tab on the given href and makes it active", () => {
    const r = openAt(snapshot(), "w1", "/inbox/pulls/42");
    expect(r.snapshot.tabs).toHaveLength(1);
    expect(r.snapshot.tabs[0].href).toBe("/inbox/pulls/42");
    expect(r.snapshot.windows[0].activeTabId).toBe(r.tabId);
    expect(r.snapshot.tabs[0].position).toBe(POSITION_GAP);
  });

  // No dedup anywhere: navigation must never move you to another tab, and an
  // explicit open makes the same promise.
  it("opens a second tab on a page that is already open", () => {
    const first = open(snapshot(), "w1", "dash-a");
    const second = open(first.snapshot, "w1", "dash-a");
    expect(second.tabId).not.toBe(first.tabId);
    expect(second.snapshot.tabs).toHaveLength(2);
  });

  it("appends new tabs after existing ones", () => {
    const a = open(snapshot(), "w1", "dash-a");
    const b = open(a.snapshot, "w1", "dash-b");
    const positions = b.snapshot.tabs
      .map((t) => t.position)
      .sort((x, y) => x - y);
    expect(positions).toEqual([POSITION_GAP, POSITION_GAP * 2]);
  });
});

describe("resetTabs", () => {
  it("removes auth-scoped metadata from every window", () => {
    const withWindows = snapshot({
      windows: [
        { id: "w1", isPrimary: true, bounds: null, activeTabId: null },
        { id: "w2", isPrimary: false, bounds: null, activeTabId: null },
      ],
    });
    const first = openAt(withWindows, "w1", "/tasks/private-a");
    const second = openAt(first.snapshot, "w2", "/inbox/private-b");

    const reset = resetTabs(second.snapshot, {
      href: "/spaces",
      makeId,
      now,
    });

    expect(reset.tabs).toHaveLength(2);
    expect(reset.tabs).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ windowId: "w1", href: "/spaces" }),
        expect.objectContaining({ windowId: "w2", href: "/spaces" }),
      ]),
    );
    expect(reset.tabs.every((tab) => tab.viewState === null)).toBe(true);
    expect(reset.windows.every((window) => window.activeTabId !== null)).toBe(
      true,
    );
  });
});

describe("setTabTarget", () => {
  // The whole location moves together: href, the view state the href cannot
  // express, and the label cache. A tab that keeps a stale field here restores
  // onto the wrong page or renders the previous page's name.
  it("writes the tab's whole location and focuses it", () => {
    const a = open(snapshot(), "w1", "dash-a");
    const b = open(a.snapshot, "w1", "dash-b");
    const s = setTabTarget(b.snapshot, {
      tabId: a.tabId,
      href: "/spaces/c1/tasks/t9",
      viewState: { listOpen: true, spaceId: "c1" },
      ...NO_IDENTITY,
      taskId: "t9",
      channelId: "c1",
      now,
    });
    const tab = s.tabs.find((t) => t.id === a.tabId);
    expect(tab?.href).toBe("/spaces/c1/tasks/t9");
    expect(tab?.viewState).toEqual({ listOpen: true, spaceId: "c1" });
    expect(tab?.taskId).toBe("t9");
    expect(tab?.dashboardId).toBeNull();
    expect(s.windows[0].activeTabId).toBe(a.tabId);
  });

  it("can retarget a background tab without focusing it", () => {
    const a = open(snapshot(), "w1", "dash-a");
    const b = open(a.snapshot, "w1", "dash-b");
    const s = setTabTarget(b.snapshot, {
      tabId: a.tabId,
      href: "/tasks/t9",
      viewState: { title: "Background task" },
      ...NO_IDENTITY,
      taskId: "t9",
      activate: false,
      now,
    });

    expect(s.tabs.find((t) => t.id === a.tabId)).toMatchObject({
      href: "/tasks/t9",
      taskId: "t9",
    });
    expect(s.windows[0].activeTabId).toBe(b.tabId);
  });

  it("ignores an unknown tab", () => {
    const a = open(snapshot(), "w1", "dash-a");
    const s = setTabTarget(a.snapshot, {
      tabId: "nope",
      href: "/loops",
      viewState: null,
      ...NO_IDENTITY,
      now,
    });
    expect(s).toBe(a.snapshot);
  });
});

describe("decideTabNavigation", () => {
  // The governing rule: a plain navigation stays in the tab you are in.
  //
  // The last two cases are why the match is on href. Identity is all-null for
  // `/loops` and `/archived` alike, and identical across a search-param change,
  // so an identity-keyed comparison read both as "already there" and the strip
  // never followed the navigation.
  it.each([
    ["a different page", "/spaces/c1", "/inbox"],
    ["two routes outside the label vocabulary", "/loops", "/archived"],
    [
      "a search-param change",
      "/spaces/c1/canvases",
      "/spaces/c1/canvases?filter=mine",
    ],
  ])("replaces the active tab's location on %s", (_case, from, to) => {
    const d = navigate({ href: to, activeTab: { id: "t1", href: from } });
    expect(d).toMatchObject({ type: "replace", tabId: "t1", href: to });
  });

  it("never activates another tab that already holds the destination", () => {
    const d = navigate({
      href: "/inbox",
      activeTab: { id: "t1", href: "/spaces/c1" },
      windowTabIds: ["t1", "t2"],
    });
    expect(d.type).toBe("replace");
  });

  it("opens a tab when there is no active one", () => {
    const d = navigate({ href: "/inbox", activeTab: null });
    expect(d).toMatchObject({ type: "open", href: "/inbox" });
  });

  it("stamps the entry when the active tab already holds the location", () => {
    const d = navigate({
      href: "/inbox",
      activeTab: { id: "t1", href: "/inbox" },
    });
    expect(d).toEqual({ type: "stamp", stampTabId: "t1" });
  });

  // The router updates location.href before the new route's params, so the
  // first pass writes the new href with the old identity. Keyed on href alone,
  // the corrected identity arriving a frame later compared equal and was
  // dropped, leaving a task tab labelled as its space forever.
  it("writes a label cache that resolves after the href did", () => {
    const d = navigate({
      href: "/spaces/c1/tasks/t9",
      activeTab: {
        id: "t1",
        href: "/spaces/c1/tasks/t9",
        identity: { ...NO_IDENTITY, channelId: "c1" },
      },
      identity: { ...NO_IDENTITY, channelId: "c1", taskId: "t9" },
    });
    expect(d).toMatchObject({ type: "replace", tabId: "t1", taskId: "t9" });
  });

  it("persists a view-state change made without navigating", () => {
    const d = decideTabNavigation({
      historyTabId: null,
      serverActiveTabId: "t1",
      activeTab: {
        id: "t1",
        href: "/spaces/c1",
        viewState: null,
        identity: NO_IDENTITY,
      },
      href: "/spaces/c1",
      viewState: { listOpen: true, spaceId: "c1" },
      identity: NO_IDENTITY,
    });
    expect(d).toMatchObject({ type: "replace", tabId: "t1" });
  });

  // Back/forward is the only thing that may move you between tabs.
  it("activates the tab a history entry is tagged with", () => {
    const d = navigate({
      href: "/spaces/c1",
      activeTab: { id: "t1", href: "/spaces/c1" },
      historyTabId: "t2",
      windowTabIds: ["t1", "t2"],
      serverActiveTabId: "t1",
    });
    expect(d).toEqual({ type: "activate", tabId: "t2" });
  });

  it("ignores a tag equal to the active tab and decides from the route", () => {
    const d = navigate({
      href: "/inbox",
      activeTab: { id: "t1", href: "/spaces/c1" },
      historyTabId: "t1",
      windowTabIds: ["t1"],
      serverActiveTabId: "t1",
    });
    expect(d).toMatchObject({ type: "replace", tabId: "t1" });
  });

  // Switching tabs must not write anything. Fed settled inputs, no frame of the
  // switch is a `replace` — the corruption this guards is a frame that pairs the
  // new tab's tag with the old tab's href, which reads as "tab B navigated to
  // A's page" and copies A's URL onto B.
  it("writes nothing across the frames of a tab switch", () => {
    const tabA = { id: "a", href: "/spaces/a" };
    const tabB = { id: "b", href: "/spaces/b" };
    const frames = [
      // Navigation pending: the settled entry is still A's, and so is its tag.
      navigate({
        href: tabA.href,
        historyTabId: "a",
        activeTab: tabA,
        serverActiveTabId: "a",
        windowTabIds: ["a", "b"],
      }),
      // Landed: the settled tag is now B, which the mirror hasn't caught up to.
      navigate({
        href: tabB.href,
        historyTabId: "b",
        activeTab: tabA,
        serverActiveTabId: "a",
        windowTabIds: ["a", "b"],
      }),
      // Focus applied: everything agrees.
      navigate({
        href: tabB.href,
        historyTabId: "b",
        activeTab: tabB,
        serverActiveTabId: "b",
        windowTabIds: ["a", "b"],
      }),
    ];

    expect(frames.map((f) => f.type)).toEqual(["stamp", "activate", "stamp"]);
  });

  it("skips a tag for a tab that has since been closed", () => {
    const d = navigate({
      href: "/inbox",
      activeTab: { id: "t1", href: "/spaces/c1" },
      historyTabId: "gone",
      windowTabIds: ["t1"],
      serverActiveTabId: "t1",
    });
    expect(d).toMatchObject({ type: "replace", tabId: "t1" });
  });
});

describe("closeTab", () => {
  it("focuses the neighbouring tab when the active tab closes", () => {
    let s = snapshot();
    const a = open(s, "w1", "dash-a");
    const b = open(a.snapshot, "w1", "dash-b");
    s = b.snapshot; // active = b
    const r = closeTab(s, b.tabId);
    expect(r.snapshot.tabs).toHaveLength(1);
    expect(r.nextActiveTabId).toBe(a.tabId);
    expect(r.snapshot.windows[0].activeTabId).toBe(a.tabId);
  });

  it("closes a secondary window when its last tab closes", () => {
    const s = snapshot({
      windows: [
        { id: "w1", isPrimary: true, bounds: null, activeTabId: null },
        { id: "w2", isPrimary: false, bounds: null, activeTabId: null },
      ],
    });
    const t = open(s, "w2", "dash-a");
    const r = closeTab(t.snapshot, t.tabId);
    expect(r.closedWindowId).toBe("w2");
    expect(r.snapshot.windows.map((w) => w.id)).toEqual(["w1"]);
  });

  it("shows the landing (null active) when the primary's last tab closes", () => {
    const t = open(snapshot(), "w1", "dash-a");
    const r = closeTab(t.snapshot, t.tabId);
    expect(r.closedWindowId).toBeNull();
    expect(r.snapshot.windows[0].activeTabId).toBeNull();
    expect(r.snapshot.tabs).toHaveLength(0);
  });
});
describe("closeTabs", () => {
  /** Open n dashboards in w1, returning the snapshot and ordered tab ids. */
  function openMany(n: number) {
    let s = snapshot();
    const ids: string[] = [];
    for (let i = 0; i < n; i++) {
      const r = open(s, "w1", `dash-${i}`);
      s = r.snapshot;
      ids.push(r.tabId);
    }
    return { s, ids };
  }

  it("is a noop for an empty or unknown id list", () => {
    const { s } = openMany(2);
    expect(closeTabs(s, [])).toBe(s);
    expect(closeTabs(s, ["nope"]).tabs).toHaveLength(2);
  });

  it("removes the given tabs and keeps the rest", () => {
    const { s, ids } = openMany(4);
    const r = closeTabs(s, [ids[1], ids[2]]);
    expect(r.tabs.map((t) => t.id)).toEqual([ids[0], ids[3]]);
    expect(r.windows).toHaveLength(1);
  });

  it("keeps the active tab focused when it survives", () => {
    const { s, ids } = openMany(3);
    const focused = closeTabs(setFocus(s, ids[0]), [ids[1], ids[2]]);
    expect(focused.windows[0].activeTabId).toBe(ids[0]);
  });

  it("focuses the anchor when the active tab is closed", () => {
    const { s, ids } = openMany(4);
    // Active is ids[1]; "close others" on anchor ids[0] closes 1,2,3 → the
    // anchor takes focus even though a stored-order neighbour differs.
    const r = closeTabs(setFocus(s, ids[1]), [ids[1], ids[2], ids[3]], ids[0]);
    expect(r.windows[0].activeTabId).toBe(ids[0]);
  });

  it("falls back to closeTab's neighbour when no anchor is given", () => {
    const { s, ids } = openMany(4);
    // Active ids[1]; closing 1,2 leaves [0,3]; the survivor at the old slot is 3.
    const r = closeTabs(setFocus(s, ids[1]), [ids[1], ids[2]]);
    expect(r.windows[0].activeTabId).toBe(ids[3]);
  });

  it("ignores an anchor when the active tab survived", () => {
    const { s, ids } = openMany(4);
    // Active ids[0] survives; anchor must not steal focus from it.
    const r = closeTabs(setFocus(s, ids[0]), [ids[2], ids[3]], ids[1]);
    expect(r.windows[0].activeTabId).toBe(ids[0]);
  });

  it("lands the primary window on channels when all tabs close", () => {
    const { s, ids } = openMany(2);
    const r = closeTabs(s, ids);
    expect(r.tabs).toHaveLength(0);
    expect(r.windows[0].activeTabId).toBeNull();
  });

  it("drops an emptied secondary window", () => {
    const base = snapshot({
      windows: [
        { id: "w1", isPrimary: true, bounds: null, activeTabId: null },
        { id: "w2", isPrimary: false, bounds: null, activeTabId: null },
      ],
    });
    const a = open(base, "w2", "dash-a");
    const b = open(a.snapshot, "w2", "dash-b");
    const r = closeTabs(b.snapshot, [a.tabId, b.tabId]);
    expect(r.windows.map((w) => w.id)).toEqual(["w1"]);
  });

  function setFocus(s: TabsSnapshot, tabId: string): TabsSnapshot {
    return {
      ...s,
      windows: s.windows.map((w) =>
        w.id === "w1" ? { ...w, activeTabId: tabId } : w,
      ),
    };
  }
});
describe("setTabOrder", () => {
  function openThree() {
    let s = snapshot();
    const ids: string[] = [];
    for (const d of ["a", "b", "c"]) {
      const r = open(s, "w1", `dash-${d}`);
      s = r.snapshot;
      ids.push(r.tabId);
    }
    return { s, ids };
  }

  function orderOf(s: TabsSnapshot): string[] {
    return s.tabs
      .filter((t) => t.windowId === "w1")
      .sort((a, b) => a.position - b.position)
      .map((t) => t.id);
  }

  it("persists the given order with clean gap positions", () => {
    const { s, ids } = openThree();
    const next = setTabOrder(s, "w1", [ids[2], ids[0], ids[1]]);
    expect(orderOf(next)).toEqual([ids[2], ids[0], ids[1]]);
    expect(
      next.tabs
        .filter((t) => t.windowId === "w1")
        .sort((a, b) => a.position - b.position)
        .map((t) => t.position),
    ).toEqual([POSITION_GAP, 2 * POSITION_GAP, 3 * POSITION_GAP]);
  });

  it("ignores unknown ids and appends unlisted tabs in old order", () => {
    const { s, ids } = openThree();
    const next = setTabOrder(s, "w1", ["nope", ids[1]]);
    expect(orderOf(next)).toEqual([ids[1], ids[0], ids[2]]);
  });

  it("leaves other windows' tabs untouched", () => {
    const base = snapshot({
      windows: [
        { id: "w1", isPrimary: true, bounds: null, activeTabId: null },
        { id: "w2", isPrimary: false, bounds: null, activeTabId: null },
      ],
    });
    const other = open(base, "w2", "dash-z");
    const r = open(other.snapshot, "w1", "dash-a");
    const next = setTabOrder(r.snapshot, "w1", [r.tabId]);
    const w2tab = next.tabs.find((t) => t.windowId === "w2");
    expect(w2tab?.position).toBe(POSITION_GAP);
  });
});
describe("primaryWindow", () => {
  it("prefers the primary window, falling back to the first", () => {
    const s = snapshot({
      windows: [
        { id: "w2", isPrimary: false, bounds: null, activeTabId: null },
        { id: "w1", isPrimary: true, bounds: null, activeTabId: null },
      ],
    });
    expect(primaryWindow(s)?.id).toBe("w1");
  });
});

describe("setWindowActiveTab", () => {
  it("focuses a tab that exists in the window", () => {
    const a = open(snapshot(), "w1", "dash-a");
    const b = open(a.snapshot, "w1", "dash-b");
    const next = setWindowActiveTab(b.snapshot, "w1", a.tabId);
    expect(next.windows[0].activeTabId).toBe(a.tabId);
  });

  it("clears focus with null (landing state)", () => {
    const a = open(snapshot(), "w1", "dash-a");
    const next = setWindowActiveTab(a.snapshot, "w1", null);
    expect(next.windows[0].activeTabId).toBeNull();
  });

  it("ignores a tab id that does not exist (dead history tag)", () => {
    const a = open(snapshot(), "w1", "dash-a");
    const next = setWindowActiveTab(a.snapshot, "w1", "closed-long-ago");
    expect(next).toBe(a.snapshot);
    expect(next.windows[0].activeTabId).toBe(a.tabId);
  });

  it("ignores a tab that belongs to another window", () => {
    const base = snapshot({
      windows: [
        { id: "w1", isPrimary: true, bounds: null, activeTabId: null },
        { id: "w2", isPrimary: false, bounds: null, activeTabId: null },
      ],
    });
    const foreign = open(base, "w2", "dash-z");
    const next = setWindowActiveTab(foreign.snapshot, "w1", foreign.tabId);
    expect(next).toBe(foreign.snapshot);
    expect(next.windows[0].activeTabId).toBeNull();
  });

  it("ignores an unknown window", () => {
    const a = open(snapshot(), "w1", "dash-a");
    expect(setWindowActiveTab(a.snapshot, "w-nope", null)).toBe(a.snapshot);
  });

  it("keeps snapshot identity when the tab is already active", () => {
    const a = open(snapshot(), "w1", "dash-a");
    expect(setWindowActiveTab(a.snapshot, "w1", a.tabId)).toBe(a.snapshot);
  });

  it("a tab closed then re-activated by a stale id never dangles", () => {
    // The persistence-bug shape: close a tab, then a back/forward replay tries
    // to focus its id. The active tab must survive untouched — a dangling
    // activeTabId makes every later navigation open a new tab.
    const a = open(snapshot(), "w1", "dash-a");
    const b = open(a.snapshot, "w1", "dash-b");
    const closed = closeTab(b.snapshot, b.tabId).snapshot;
    const next = setWindowActiveTab(closed, "w1", b.tabId);
    expect(next).toBe(closed);
    expect(next.windows[0].activeTabId).toBe(a.tabId);
    expect(next.tabs.some((t) => t.id === next.windows[0].activeTabId)).toBe(
      true,
    );
  });
});
