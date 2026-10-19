import { describe, expect, it } from "vitest";
import { reportScopeParams } from "./reportScope";

describe("reportScopeParams", () => {
  it.each([
    ["entire-project", "user-1", {}],
    ["entire-project", undefined, {}],
    ["for-you", "user-1", { suggested_reviewers: "user-1" }],
    ["for-you", "  user-1 ", { suggested_reviewers: "user-1" }],
    ["for-you", undefined, null],
    ["for-you", null, null],
    ["for-you", "   ", null],
  ] as const)("%s with uuid %j", (scope, uuid, expected) => {
    expect(reportScopeParams(scope, uuid)).toEqual(expected);
  });
});
