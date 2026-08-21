import { describe, expect, it } from "vitest";
import { railPaneForRouteId, railPaneHasSidebar } from "./railPane";

describe("railPaneForRouteId", () => {
  it.each([
    ["/website/home", "home"],
    ["/website/activity", "activity"],
    ["/website/command-center", "command-center"],
    ["/command-center", "command-center"],
    ["/code/inbox", "inbox"],
    ["/code/inbox/pulls/$reportId", "inbox"],
    ["/code/loops", "loops"],
    ["/code/loops/$loopId/edit", "loops"],
  ] as const)("puts %s on %s", (routeId, pane) => {
    expect(railPaneForRouteId(routeId)).toBe(pane);
  });

  // A space page is a space page whatever it is called. The lookalikes are the
  // reason this matches route ids rather than path text.
  it.each([
    "/website/",
    "/website/$channelId/",
    "/website/$channelId/loops",
    "/website/$channelId/context",
    "/website/$channelId/history",
    "/website/$channelId/canvases",
    "/website/$channelId/tasks/$taskId",
    "/website/feeds/$feedId",
    "/code/tasks/$taskId",
  ])("leaves %s with Spaces", (routeId) => {
    expect(railPaneForRouteId(routeId)).toBe("spaces");
  });
});

describe("railPaneHasSidebar", () => {
  it.each(["home", "inbox", "command-center", "loops"] as const)(
    "gives %s the whole screen",
    (pane) => {
      expect(railPaneHasSidebar(pane)).toBe(false);
    },
  );

  it.each(["spaces", "activity"] as const)("gives %s a column", (pane) => {
    expect(railPaneHasSidebar(pane)).toBe(true);
  });
});
