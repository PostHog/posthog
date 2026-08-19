import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let currentUserLoading = false;
let membersError: Error | null = null;
let taskQueryError: Error | null = null;
const refetch = vi.fn();
const refetchMembers = vi.fn();

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => null,
}));
vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => ({ data: null, isLoading: currentUserLoading }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useOrgMembers", () => ({
  useOrgMembers: () => ({
    members: [],
    error: membersError,
    isLoading: false,
    isError: membersError !== null,
    isComplete: true,
    refetch: refetchMembers,
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
    membersError = null;
    taskQueryError = null;
    refetch.mockClear();
    refetchMembers.mockClear();
  });

  it("waits for the current user before resolving an @me filter", () => {
    currentUserLoading = true;

    const { result } = renderHook(() => useFeedQueryPlan("created-by:@me"));

    expect(result.current.isLoading).toBe(true);
    expect(result.current.plan).toBeUndefined();
  });

  it("stops planning when member lookup fails", () => {
    membersError = new Error("Network error");

    const { result } = renderHook(() => useFeedQueryPlan("created-by:alex"));

    expect(result.current.error).toBe(membersError);
    expect(result.current.plan).toBeUndefined();
  });

  it("exposes task request failures instead of empty results", () => {
    taskQueryError = new Error("Network error");

    const { result } = renderHook(() => useTaskFeedResults("billing"));

    expect(result.current.error).toBe(taskQueryError);
    expect(result.current.tasks).toEqual([]);
  });
});
