import { beforeEach, describe, expect, it } from "vitest";
import { useCommentNavigationStore } from "./commentNavigationStore";

const artifact = { scope: "task_artifact", itemId: "a" } as const;
const canvas = { scope: "desktop_canvas", itemId: "c" } as const;

describe("commentNavigationStore", () => {
  beforeEach(() => {
    useCommentNavigationStore.setState({
      focusByTask: {},
      resolutionsByTarget: {},
    });
  });

  // Picking the same thread again has to scroll again, so the request is the
  // nonce rather than the thread id.
  it("bumps the nonce for a repeated request", () => {
    const { requestCommentFocus } = useCommentNavigationStore.getState();

    requestCommentFocus("task-1", artifact, "comment-1");
    const first = useCommentNavigationStore.getState().focusByTask["task-1"];
    requestCommentFocus("task-1", artifact, "comment-1");
    const second = useCommentNavigationStore.getState().focusByTask["task-1"];

    expect(first?.threadId).toBe("comment-1");
    expect(second?.nonce).toBe((first?.nonce ?? 0) + 1);
    expect(second?.openCommentsTab).toBe(true);
  });

  it("acknowledges the tab-open request without losing durable focus", () => {
    const { requestCommentFocus, acknowledgeCommentsTabOpen } =
      useCommentNavigationStore.getState();
    requestCommentFocus("task-1", artifact, "comment-1");
    const focus = useCommentNavigationStore.getState().focusByTask["task-1"];

    acknowledgeCommentsTabOpen("task-1", focus?.nonce ?? -1);

    expect(
      useCommentNavigationStore.getState().focusByTask["task-1"],
    ).toMatchObject({
      threadId: "comment-1",
      openCommentsTab: false,
    });
  });

  it("keeps each task's focus to itself", () => {
    const { requestCommentFocus } = useCommentNavigationStore.getState();

    requestCommentFocus("task-1", artifact, "comment-1");
    requestCommentFocus("task-2", canvas, "comment-2");

    const { focusByTask } = useCommentNavigationStore.getState();
    expect(focusByTask["task-1"]?.threadId).toBe("comment-1");
    expect(focusByTask["task-1"]?.target).toEqual(artifact);
    expect(focusByTask["task-2"]?.threadId).toBe("comment-2");
  });

  // The surfaces recompute anchors on every scroll and resize; an unchanged
  // result must not re-render the list that reads them.
  it("ignores a resolution update that changes nothing", () => {
    const { setCommentResolutions } = useCommentNavigationStore.getState();

    setCommentResolutions(artifact, new Map([["comment-1", "exact"]]));
    const first = useCommentNavigationStore.getState().resolutionsByTarget;
    setCommentResolutions(artifact, new Map([["comment-1", "exact"]]));
    const second = useCommentNavigationStore.getState().resolutionsByTarget;
    setCommentResolutions(artifact, new Map([["comment-1", "orphaned"]]));
    const third = useCommentNavigationStore.getState().resolutionsByTarget;

    expect(second).toBe(first);
    expect(third).not.toBe(second);
    expect(third["task_artifact:a"]?.get("comment-1")).toBe("orphaned");
  });
});
