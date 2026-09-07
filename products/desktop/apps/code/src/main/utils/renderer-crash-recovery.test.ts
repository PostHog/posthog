import { describe, expect, it } from "vitest";
import {
  appRouteFromUrl,
  createRouteCrashTracker,
} from "./renderer-crash-recovery";

describe("renderer crash recovery", () => {
  it.each([
    [
      "file:///app.asar/.vite/renderer/main_window/index.html#/spaces/s1/tasks/t1",
      "/spaces/s1/tasks/t1",
    ],
    ["http://localhost:5173/?quarantinedRoute=%2Fa#/code", "/code"],
    ["file:///app.asar/index.html", null],
    ["file:///app.asar/index.html#not-a-route", null],
  ])("reads the route out of %s", (url, expected) => {
    expect(appRouteFromUrl(url)).toBe(expected);
  });

  it("quarantines a route only once it has crashed twice", () => {
    const tracker = createRouteCrashTracker();
    expect(tracker.record("/spaces/s1/tasks/t1", 0)).toBe(false);
    expect(tracker.record("/spaces/s1/tasks/t1", 5_000)).toBe(true);
  });

  it("does not quarantine two crashes far apart", () => {
    const tracker = createRouteCrashTracker();
    expect(tracker.record("/spaces/s1/tasks/t1", 0)).toBe(false);
    expect(tracker.record("/spaces/s1/tasks/t1", 120_000)).toBe(false);
  });

  it("does not quarantine one crash each on two routes", () => {
    const tracker = createRouteCrashTracker();
    expect(tracker.record("/spaces/s1/tasks/t1", 0)).toBe(false);
    expect(tracker.record("/spaces/s1/tasks/t2", 1_000)).toBe(false);
  });
});
