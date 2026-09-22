import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  reportsInboxEnabled: true,
  currentUser: {
    data: { uuid: "user-1" } as { uuid: string } | undefined,
    isLoading: false,
  },
  useInboxReports: vi.fn(() => ({
    data: { count: 1, results: [{ id: "report-1" }] },
    isLoading: false,
  })),
}));

vi.mock("@posthog/ui/features/auth/store", () => ({
  useAuthStateValue: () => "us:1",
}));
vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({}),
}));
vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => mocks.currentUser,
}));
vi.mock("@posthog/ui/features/inbox/hooks/useInboxReports", () => ({
  useInboxReports: mocks.useInboxReports,
}));
vi.mock("@posthog/ui/features/feature-flags/useReportsInboxEnabled", () => ({
  useReportsInboxEnabled: () => mocks.reportsInboxEnabled,
}));

import { useActivityFilterStore } from "@posthog/ui/features/canvas/stores/activityFilterStore";
import { useInboxActivityPreview } from "./useInboxActivityPreview";

describe("useInboxActivityPreview", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.reportsInboxEnabled = true;
    mocks.currentUser = {
      data: { uuid: "user-1" },
      isLoading: false,
    };
    useActivityFilterStore.setState({
      inboxEnabledByAuthIdentity: { "us:1": true },
      inboxScope: "for-you",
      inboxSourceProductFilter: [],
      inboxPrFilter: "all",
      inboxSortField: "priority",
      inboxSortDirection: "asc",
      inboxPriorityFilter: ["P1"],
    });
  });

  it("requests the default P1 reports assigned to the current user", () => {
    renderHook(() => useInboxActivityPreview());

    expect(mocks.useInboxReports).toHaveBeenCalledWith(
      expect.objectContaining({
        has_implementation_pr: undefined,
        limit: 3,
        ordering: "status,priority,-created_at",
        priority: "P1",
        source_product: undefined,
        suggested_reviewers: "user-1",
        status: "ready",
      }),
      expect.objectContaining({ enabled: true, refetchInterval: 60_000 }),
    );
  });

  it("applies the Activity inbox filters without a reviewer in project scope", () => {
    useActivityFilterStore.setState({
      inboxScope: "entire-project",
      inboxSourceProductFilter: ["github", "session_replay"],
      inboxPrFilter: "without_pr",
      inboxSortField: "created_at",
      inboxSortDirection: "desc",
      inboxPriorityFilter: ["P0", "P2"],
    });

    renderHook(() => useInboxActivityPreview());

    expect(mocks.useInboxReports).toHaveBeenCalledWith(
      expect.objectContaining({
        has_implementation_pr: false,
        ordering: "status,-created_at,priority",
        priority: "P0,P2",
        source_product: "github,session_replay",
        suggested_reviewers: undefined,
      }),
      expect.objectContaining({ enabled: true }),
    );
  });

  it("stays loading while the For you reviewer is unresolved", () => {
    mocks.currentUser = { data: undefined, isLoading: true };

    const { result } = renderHook(() => useInboxActivityPreview());

    expect(result.current.isLoading).toBe(true);
    expect(mocks.useInboxReports).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ enabled: false }),
    );
  });

  it.each([
    [
      "the project rollout is off",
      () => {
        mocks.reportsInboxEnabled = false;
      },
    ],
    [
      "the project has not opted in",
      () => useActivityFilterStore.setState({ inboxEnabledByAuthIdentity: {} }),
    ],
  ])(
    "hides cached reports and disables the query when %s",
    (_name, disable) => {
      disable();

      const { result } = renderHook(() => useInboxActivityPreview());

      expect(result.current).toEqual({
        reports: [],
        totalCount: 0,
        isLoading: false,
        isIncluded: false,
      });
      expect(mocks.useInboxReports).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({ enabled: false }),
      );
    },
  );
});
