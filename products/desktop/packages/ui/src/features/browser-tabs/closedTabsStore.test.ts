import type { TabIdentity, TabLocation } from "@posthog/shared";
import { beforeEach, describe, expect, it } from "vitest";
import {
  type ClosedTab,
  closedTabRecord,
  MAX_CLOSED_TABS,
  useClosedTabsStore,
} from "./closedTabsStore";

function closedTab(href: string | null): TabLocation & TabIdentity {
  return {
    href,
    viewState: null,
    dashboardId: null,
    taskId: null,
    channelId: null,
    channelSection: null,
    appView: null,
  };
}

function record(...hrefs: string[]): void {
  useClosedTabsStore
    .getState()
    .record(hrefs.map((href) => closedTabRecord(closedTab(href)) as ClosedTab));
}

describe("closedTabsStore", () => {
  beforeEach(() => {
    useClosedTabsStore.setState({ closed: [] });
  });

  it("pops the most recently closed tab first", () => {
    const { take } = useClosedTabsStore.getState();
    record("/one", "/two");
    expect(take()?.href).toBe("/two");
    expect(take()?.href).toBe("/one");
    expect(take()).toBeNull();
  });

  it("drops the oldest entries past the cap", () => {
    for (let i = 0; i <= MAX_CLOSED_TABS; i++) record(`/${i}`);
    const { closed } = useClosedTabsStore.getState();
    expect(closed).toHaveLength(MAX_CLOSED_TABS);
    expect(closed[0].href).toBe("/1");
  });

  // A tab with no href has nothing to navigate back to, so recording it would
  // make the shortcut look broken: a press that consumes a slot and opens
  // nothing.
  it("has no record for a tab without an href", () => {
    expect(closedTabRecord(closedTab(null))).toBeNull();
    expect(closedTabRecord(closedTab("/one"))?.href).toBe("/one");
  });

  it("carries the view state and label cache a reopen restores", () => {
    const viewState = { listOpen: true, spaceId: "s1" };
    expect(
      closedTabRecord({
        ...closedTab("/spaces/s1"),
        viewState,
        channelId: "s1",
      }),
    ).toMatchObject({ href: "/spaces/s1", viewState, channelId: "s1" });
  });
});
