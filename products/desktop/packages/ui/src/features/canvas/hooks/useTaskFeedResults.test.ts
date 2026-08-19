import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let currentUserLoading = false;

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

import { useFeedQueryPlan } from "./useTaskFeedResults";

describe("useFeedQueryPlan", () => {
  beforeEach(() => {
    currentUserLoading = false;
  });

  it("waits for the current user before resolving an @me filter", () => {
    currentUserLoading = true;

    const { result } = renderHook(() => useFeedQueryPlan("created-by:@me"));

    expect(result.current).toEqual({ isLoading: true, plan: undefined });
  });
});
