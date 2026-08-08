import { describe, expect, it } from "vitest";
import { commentCacheCoversTarget } from "./useComments";

const target = { scope: "task_artifact", itemId: "a" } as const;

describe("commentCacheCoversTarget", () => {
  // Optimistic writes must stay within the exact resource cache.
  it.each([
    {
      what: "the target's own query",
      key: ["comments", "identity", "task-1", "task_artifact", "a"],
      covers: true,
    },
    {
      what: "a sibling resource's query",
      key: ["comments", "identity", "task-1", "task_artifact", "b"],
      covers: false,
    },
    {
      what: "the same id under another scope",
      key: ["comments", "identity", "task-1", "desktop_canvas", "a"],
      covers: false,
    },
    {
      what: "an unrelated query",
      key: ["artifactPreview", "identity", "task_artifact", "a"],
      covers: false,
    },
  ])("$what", ({ key, covers }) => {
    expect(commentCacheCoversTarget(key, target)).toBe(covers);
  });
});
