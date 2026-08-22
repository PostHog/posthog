import { describe, expect, it } from "vitest";
import { railPaneForRouteId, railPaneHasSidebar } from "./railPane";

describe("railPaneForRouteId", () => {
  it.each([
    ["/_channels/home", "home"],
    ["/_channels/activity", "activity"],
    ["/_channels/feeds/$feedId", "activity"],
    ["/command-center", "command-center"],
    ["/inbox", "inbox"],
    ["/inbox/pulls/$reportId", "inbox"],
    ["/agents", "inbox"],
    ["/agents/scouts/$skillName", "inbox"],
    ["/settings/$category", "settings"],
    ["/folders/$folderId", "settings"],
  ] as const)("puts %s on %s", (routeId, pane) => {
    expect(railPaneForRouteId(routeId)).toBe(pane);
  });

  // A space page is a space page whatever it is called. The lookalikes are the
  // reason this matches route ids rather than path text.
  it.each([
    "/spaces/",
    "/spaces/$channelId/",
    "/spaces/$channelId/loops",
    "/spaces/$channelId/context",
    "/spaces/$channelId/history",
    "/spaces/$channelId/canvases",
    "/spaces/$channelId/dashboards/$dashboardId",
    "/_channels/new",
    "/_channels/tasks/$taskId",
    "/tasks/pending/$key",
    "/archive",
    "/pr",
  ])("leaves %s with Spaces", (routeId) => {
    expect(railPaneForRouteId(routeId)).toBe("spaces");
  });

  it.each(["/_channels/loops/undefined", "/agentsX"])(
    "does not claim a lookalike prefix: %s",
    (routeId) => {
      expect(railPaneForRouteId(routeId)).toBeNull();
    },
  );
});

describe("railPaneHasSidebar", () => {
  it.each(["home", "inbox", "command-center", "loops", "settings"] as const)(
    "gives %s the whole screen",
    (pane) => {
      expect(railPaneHasSidebar(pane)).toBe(false);
    },
  );

  it.each(["spaces", "activity"] as const)("gives %s a column", (pane) => {
    expect(railPaneHasSidebar(pane)).toBe(true);
  });
});
