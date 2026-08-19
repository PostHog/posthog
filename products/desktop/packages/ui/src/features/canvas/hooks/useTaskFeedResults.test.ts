import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let currentUserLoading = false;
let taskQueryError: Error | null = null;
const refetch = vi.fn();

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => null,
}));
vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => ({ data: null, isLoading: currentUserLoading }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useOrgMembers", () => ({
  useOrgMembers: () => ({
    members: [],
    isLoading: false,
    isError: false,
    isComplete: true,
  }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: [], isLoading: false }),
}));
vi.mock("@posthog/ui/hooks/useAuthenticatedQuery", () => ({
  useAuthenticatedQuery: () => ({
    data: undefined,
    error: taskQueryError,
    isFetching: false,
    isLoading: false,
    refetch,
  }),
}));

import { useFeedQueryPlan, useTaskFeedResults } from "./useTaskFeedResults";

describe("task feed queries", () => {
  beforeEach(() => {
    currentUserLoading = false;
    taskQueryError = null;
    refetch.mockClear();
  });

  it("waits for the current user before resolving an @me filter", () => {
    currentUserLoading = true;

    const { result } = renderHook(() => useFeedQueryPlan("created-by:@me"));

    expect(result.current).toEqual({ isLoading: true, plan: undefined });
  });

  it("exposes task request failures instead of empty results", () => {
    taskQueryError = new Error("Network error");

    const { result } = renderHook(() => useTaskFeedResults("billing"));

    expect(result.current.error).toBe(taskQueryError);
    expect(result.current.tasks).toEqual([]);
  });
});
