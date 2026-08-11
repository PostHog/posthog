import { describe, expect, it } from "vitest";
import { commentCacheCoversTarget } from "./useComments";

const target = { scope: "task_artifact", itemId: "a" } as const;

describe("commentCacheCoversTarget", () => {
  // An optimistic reply has to land in every list showing that resource — the
  // artifact's own query and the task-wide fan-out — and in no other.
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
      what: "a fan-out including the target",
      key: [
        "comments",
        "targets",
        "identity",
        "task-1",
        "desktop_canvas:c,task_artifact:a",
      ],
      covers: true,
    },
    {
      what: "a fan-out without the target",
      key: ["comments", "targets", "identity", "task-1", "task_artifact:b"],
      covers: false,
    },
    {
      what: "a fan-out whose target only shares a prefix",
      key: ["comments", "targets", "identity", "task-1", "task_artifact:ab"],
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
