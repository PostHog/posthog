import { beforeEach, describe, expect, it } from "vitest";
import { useReviewNavigationStore } from "./reviewNavigationStore";

describe("reviewNavigationStore", () => {
  beforeEach(() => {
    useReviewNavigationStore.setState({
      activeFilePaths: {},
      scrollRequests: {},
      reviewModes: {},
      commentFileFilters: {},
    });
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
