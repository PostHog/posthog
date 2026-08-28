import { describe, expect, it } from "vitest";
import { shouldRefuseInternalChildBoot } from "./internal-child-guard";

describe("shouldRefuseInternalChildBoot", () => {
  it.each([
    ["packaged app inside the internal child tree", true, "1", true],
    ["packaged app with no marker", true, undefined, false],
    ["dev build inside the internal child tree", false, "1", false],
    ["packaged app with an empty marker", true, "", false],
  ] as const)("%s", (_name, isPackaged, marker, expected) => {
    expect(
      shouldRefuseInternalChildBoot(isPackaged, {
        POSTHOG_CODE_INTERNAL_CHILD: marker,
      }),
    ).toBe(expected);
  });
});
