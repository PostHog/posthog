import {
  ANONYMOUS_AUTH_STATE,
  useAuthStore,
} from "@posthog/ui/features/auth/store";
import {
  type TaskFeed,
  useTaskFeedsStore,
} from "@posthog/ui/features/canvas/stores/taskFeedsStore";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useProjectTaskFeed, useProjectTaskFeeds } from "./useProjectTaskFeeds";

function feed(id: string, projectId: number): TaskFeed {
  return {
    id,
    projectId,
    name: id,
    query: "billing",
    createdAt: "2026-08-01T00:00:00Z",
  };
}

function selectProject(projectId: number | null): void {
  useAuthStore.setState({
    authState: { ...ANONYMOUS_AUTH_STATE, currentProjectId: projectId },
  });
}

describe("useProjectTaskFeeds", () => {
  beforeEach(() => {
    useTaskFeedsStore.setState({
      feeds: [feed("in-project", 1), feed("other-project", 2)],
    });
    selectProject(1);
  });

  it("lists only the searches saved in the project you are in", () => {
    const { result } = renderHook(() => useProjectTaskFeeds());

    expect(result.current.map((f) => f.id)).toEqual(["in-project"]);
  });

  it("swaps the searches when the project changes", () => {
    const { result } = renderHook(() => useProjectTaskFeeds());

    act(() => selectProject(2));

    expect(result.current.map((f) => f.id)).toEqual(["other-project"]);
  });

  it("hides a search saved in another project when opened by id", () => {
    const { result } = renderHook(() => useProjectTaskFeed("other-project"));

    expect(result.current).toBeUndefined();
  });
});
