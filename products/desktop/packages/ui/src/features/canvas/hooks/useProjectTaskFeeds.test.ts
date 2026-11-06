import {
  ANONYMOUS_AUTH_STATE,
  useAuthStore,
} from "@posthog/ui/features/auth/store";
import {
  type TaskFeed,
  useTaskFeedsStore,
} from "@posthog/ui/features/canvas/stores/taskFeedsStore";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let currentUserId = "user-1";

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => null,
}));
vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => ({ data: { uuid: currentUserId } }),
}));

import { useProjectTaskFeed, useProjectTaskFeeds } from "./useProjectTaskFeeds";

function feed(id: string, projectId: number, ownerId = "user-1"): TaskFeed {
  return {
    id,
    projectId,
    ownerId,
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
    currentUserId = "user-1";
    useTaskFeedsStore.setState({
      feeds: [
        feed("in-project", 1),
        feed("other-project", 2),
        feed("other-user", 1, "user-2"),
      ],
    });
    selectProject(1);
  });

  it("lists only the searches saved in the project you are in", () => {
    const { result } = renderHook(() => useProjectTaskFeeds());

    expect(result.current.map((f) => f.id)).toEqual(["in-project"]);
  });

  it("hides searches saved by another user in the same project", () => {
    const { result, rerender } = renderHook(() => useProjectTaskFeeds());

    currentUserId = "user-2";
    rerender();

    expect(result.current.map((f) => f.id)).toEqual(["other-user"]);
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
