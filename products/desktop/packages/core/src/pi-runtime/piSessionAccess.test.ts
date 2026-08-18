import { describe, expect, it } from "vitest";
import { canPromptPiSession } from "./piSessionAccess";

describe("canPromptPiSession", () => {
  it.each([
    ["the session owner", "owner", "owner", true],
    ["another user", "owner", "viewer", false],
    ["a viewer whose identity is loading", "owner", undefined, false],
    ["a session without an owner", undefined, "viewer", true],
  ])("allows %s to prompt: %s", (_case, ownerUuid, userUuid, expected) => {
    expect(canPromptPiSession(ownerUuid, userUuid)).toBe(expected);
  });
});
