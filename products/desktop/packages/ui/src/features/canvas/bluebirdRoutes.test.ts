import { describe, expect, it } from "vitest";
import { isBluebirdOnlyPath } from "./bluebirdRoutes";

describe("isBluebirdOnlyPath", () => {
  // These paths lost the `/website` prefix that used to mark them flag-only, so
  // nothing but this list stops a flag-off user restoring one.
  it.each([
    "/spaces",
    "/spaces/chan-1",
    "/spaces/chan-1/tasks/task-1",
    "/activity",
    "/feeds/feed-1",
  ])("claims %s", (path) => {
    expect(isBluebirdOnlyPath(path)).toBe(true);
  });

  it.each(["/", "/new", "/inbox", "/loops", "/command-center", "/spacesuit"])(
    "leaves %s alone",
    (path) => {
      expect(isBluebirdOnlyPath(path)).toBe(false);
    },
  );
});
