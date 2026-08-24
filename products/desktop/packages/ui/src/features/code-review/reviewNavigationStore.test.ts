import { beforeEach, describe, expect, it } from "vitest";
import { useReviewNavigationStore } from "./reviewNavigationStore";

describe("reviewNavigationStore", () => {
  beforeEach(() => {
    useReviewNavigationStore.setState({
      activeFilePaths: {},
      scrollRequests: {},
      reviewModes: {},
      selectedPrUrls: {},
      commentFileFilters: {},
      hideViewedFiles: {},
    });
  });

  it("keeps a selected PR until the review closes", () => {
    const store = useReviewNavigationStore.getState();
    store.setSelectedPrUrl("task-1", "https://github.com/acme/repo/pull/2");
    store.setReviewMode("task-1", "split");

    expect(useReviewNavigationStore.getState().selectedPrUrls["task-1"]).toBe(
      "https://github.com/acme/repo/pull/2",
    );

    store.setReviewMode("task-1", "closed");

    expect(
      useReviewNavigationStore.getState().selectedPrUrls["task-1"],
    ).toBeUndefined();
  });

  it("stores and clears the viewed-file filter per task", () => {
    const store = useReviewNavigationStore.getState();
    store.setHideViewedFiles("task-1", true);

    expect(useReviewNavigationStore.getState().hideViewedFiles["task-1"]).toBe(
      true,
    );

    store.clearTask("task-1");
    expect(useReviewNavigationStore.getState().hideViewedFiles["task-1"]).toBe(
      false,
    );
  });

  it("clears the comment filter when navigating to a file", () => {
    const store = useReviewNavigationStore.getState();
    store.setCommentFileFilter("task-1", "unresolved");

    store.requestScrollToFile("task-1", "src/example.ts");

    const state = useReviewNavigationStore.getState();
    expect(state.scrollRequests["task-1"]).toBe("src/example.ts");
    expect(state.commentFileFilters["task-1"]).toBe("none");
  });
});
