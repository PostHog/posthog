import { describe, expect, it } from "vitest";
import {
  RAIL_PANE_ROOT,
  railPaneForPath,
  railPaneHasSidebar,
} from "./railPane";

describe("railPaneForPath", () => {
  it.each([
    ["/", "home"],
    ["/activity", "activity"],
    ["/command-center", "command-center"],
    ["/inbox", "inbox"],
    ["/inbox/pulls/$reportId", "inbox"],
    ["/loops", "loops"],
    ["/loops/$loopId/edit", "loops"],
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
    "/feeds/$feedId",
    "/tasks/$taskId",
    "/new",
  ])("leaves %s with Spaces", (path) => {
    expect(railPaneForPath(path)).toBe("spaces");
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

describe("RAIL_PANE_ROOT", () => {
  // Each destination's root has to belong to that destination, or a pick with
  // nothing remembered would land somewhere the rail then lights differently.
  it.each(Object.entries(RAIL_PANE_ROOT))("%s roots at %s", (pane, root) => {
    expect(railPaneForPath(root)).toBe(pane);
  });
});
