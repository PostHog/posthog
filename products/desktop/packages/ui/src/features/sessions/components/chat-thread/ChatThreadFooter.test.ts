import { describe, expect, it } from "vitest";
import { resolvePendingPermissionVisibility } from "./pendingPermissionVisibility";

describe("resolvePendingPermissionVisibility", () => {
  it.each([
    [undefined, 0, false],
    [undefined, 1, true],
    [true, 0, true],
    [false, 1, false],
  ])(
    "uses override %s with %i stored permissions",
    (override, storedCount, expected) => {
      expect(resolvePendingPermissionVisibility(override, storedCount)).toBe(
        expected,
      );
    },
  );
});
