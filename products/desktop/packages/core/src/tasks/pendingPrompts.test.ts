import { describe, expect, it } from "vitest";
import {
  buildPendingPromptKey,
  capPendingPrompts,
  listPendingPromptsNewestFirst,
} from "./pendingPrompts";

describe("pending prompts", () => {
  it("keeps the newest prompts up to the limit", () => {
    expect(
      capPendingPrompts(
        {
          old: { createdAt: 1 },
          middle: { createdAt: 2 },
          newest: { createdAt: 3 },
        },
        2,
      ),
    ).toEqual({ middle: { createdAt: 2 }, newest: { createdAt: 3 } });
  });

  it("orders prompts newest first", () => {
    const prompts = { old: { createdAt: 1 }, new: { createdAt: 2 } };
    expect(
      listPendingPromptsNewestFirst(prompts).map(({ key }) => key),
    ).toEqual(["new", "old"]);
  });

  it.each([
    ["uuid", 1, "abc", "uuid"],
    [null, 123, "abc", "pending-123-abc"],
  ])("builds a portable pending key", (uuid, timestamp, entropy, expected) => {
    expect(buildPendingPromptKey(uuid, timestamp, entropy)).toBe(expected);
  });
});
