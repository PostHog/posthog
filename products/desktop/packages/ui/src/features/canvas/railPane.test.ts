import { useRailSurface } from "@posthog/ui/features/canvas/hooks/useRailSurface";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  isRestorableVisitHref,
  RAIL_PANE_ROOT,
  railPaneForHref,
  railPaneForPath,
  railPaneHasSidebar,
} from "./railPane";

const routing = vi.hoisted(() => ({ href: "/inbox", channelsLayout: true }));

vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => routing.channelsLayout,
}));

vi.mock("@tanstack/react-router", () => ({
  useRouterState: ({
    select,
  }: {
    select: (state: {
      location: { href: string; pathname: string };
    }) => unknown;
  }) =>
    select({
      location: { href: routing.href, pathname: routing.href.split("?")[0] },
    }),
}));

describe("railPaneForPath", () => {
  it.each([
    ["/", "home"],
    ["/activity", "activity"],
    ["/command-center", "command-center"],
    ["/inbox", "inbox"],
    ["/reports/$reportId", "reports"],
    ["/inbox/pulls/$reportId", "inbox"],
    ["/loops", "loops"],
    ["/loops/$loopId/edit", "loops"],
    ["/feeds/", "feeds"],
    ["/feeds/$feedId", "feeds"],
  ] as const)("puts %s on %s", (path, pane) => {
    expect(railPaneForPath(path)).toBe(pane);
  });

  // Home is every path's prefix, so a prefix test would hand it the whole app.
  it.each(["/activity", "/inbox", "/spaces/$channelId", "/tasks/$taskId"])(
    "does not let Home claim %s",
    (path) => {
      expect(railPaneForPath(path)).not.toBe("home");
    },
  );

  // A space page is a space page whatever it is called. Matching the route
  // pattern rather than the resolved URL is what keeps a space named "loops"
  // from impersonating the Loops destination.
  it.each([
    "/spaces",
    "/spaces/$channelId",
    "/spaces/$channelId/loops",
    "/spaces/$channelId/context",
    "/spaces/$channelId/history",
    "/spaces/$channelId/canvases",
    "/spaces/$channelId/tasks/$taskId",
    "/tasks/$taskId",
    "/new",
  ])("leaves %s with Spaces", (path) => {
    expect(railPaneForPath(path)).toBe("spaces");
  });
});

describe("railPaneForHref", () => {
  it.each([
    ["/reports/report-1?from=%2Finbox", "inbox"],
    ["/reports/report-1?from=%2Finbox%2Ftriage", "inbox"],
    ["/reports/report-1?from=%2Fspaces%2Fchan-1", "spaces"],
    ["/reports/report-1", "reports"],
    ["/inbox?item=1", "inbox"],
  ] as const)("puts %s on %s", (href, pane) => {
    expect(railPaneForHref(href)).toBe(pane);
  });
});

describe("isRestorableVisitHref", () => {
  it.each([
    ["spaces", "/spaces/chan-1/tasks/task-1"],
    ["spaces", "/tasks/task-1"],
    ["spaces", "/new"],
    ["activity", "/activity?task=task-1"],
    ["inbox", "/inbox/pulls/report-1"],
    ["inbox", "/inbox/triage"],
    ["inbox", "/reports/report-1?from=%2Finbox"],
    ["home", "/"],
  ] as const)("lets %s replay %s", (pane, href) => {
    expect(isRestorableVisitHref(pane, href)).toBe(true);
  });

  it.each([
    ["spaces", "/settings"],
    ["spaces", "/settings/general"],
    ["spaces", "/settings/general?from=rail"],
    ["spaces", "/folders/folder-1"],
    ["spaces", "/skills"],
    ["spaces", "/mcp-servers"],
    ["spaces", "/usage"],
    ["inbox", "/inbox/agents"],
    ["spaces", "/activity"],
    ["activity", "/spaces/chan-1"],
    ["activity", "/reports/report-1?from=%2Finbox"],
    ["reports", "/reports/report-1?from=%2Finbox"],
  ] as const)("does not let %s replay %s", (pane, href) => {
    expect(isRestorableVisitHref(pane, href)).toBe(false);
  });
});

describe("railPaneHasSidebar", () => {
  it.each([true, false])(
    "hides the sidebar only on triage with channels layout %s",
    (channelsLayout) => {
      routing.channelsLayout = channelsLayout;
      routing.href = "/inbox/triage";
      useSidebarStore.setState({
        open: true,
        hasUserSetOpen: true,
        width: 320,
      });
      const { result, rerender } = renderHook(() => useRailSurface());
      expect(result.current.hasSidebar).toBe(false);
      expect(result.current.pane).toBe("inbox");

      for (const [href, hasSidebar] of [
        ["/inbox", true],
        ["/inbox/triage/", false],
        ["/reports/report-1?from=%2Finbox%2Ftriage", true],
        ["/inbox/triage?reportId=report-1", false],
        ["/inbox/reports", true],
      ] as const) {
        routing.href = href;
        rerender();
        expect(result.current.hasSidebar).toBe(hasSidebar);
      }
      expect(useSidebarStore.getState()).toMatchObject({
        open: true,
        hasUserSetOpen: true,
        width: 320,
      });
    },
  );

  it.each(["home", "reports", "command-center", "loops"] as const)(
    "gives %s the whole screen",
    (pane) => {
      expect(railPaneHasSidebar(pane)).toBe(false);
    },
  );

  it.each(["spaces", "activity", "feeds", "inbox"] as const)(
    "gives %s a column",
    (pane) => {
      expect(railPaneHasSidebar(pane)).toBe(true);
    },
  );
});

describe("RAIL_PANE_ROOT", () => {
  // Each destination's root has to belong to that destination, or a pick with
  // nothing remembered would land somewhere the rail then lights differently.
  it.each(Object.entries(RAIL_PANE_ROOT))("%s roots at %s", (pane, root) => {
    expect(railPaneForPath(root)).toBe(pane);
  });
});
