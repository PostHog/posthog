import { ApiRequestError } from "@posthog/api-client/fetcher";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockListAgentFleetApprovals = vi.hoisted(() => vi.fn());
const mockClient = vi.hoisted(() => ({
  listAgentFleetApprovals: mockListAgentFleetApprovals,
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => mockClient,
}));

vi.mock("../../auth/store", () => ({
  useAuthStateValue: <T,>(
    selector: (state: { currentProjectId: number }) => T,
  ) => selector({ currentProjectId: 2 }),
}));

import { isApprovalsPermissionError } from "./approvalsPermission";
import { useAgentFleetApprovals } from "./useAgentFleetApprovals";

function renderApprovalsHook() {
  const queryClient = new QueryClient({
    // Zero out the backoff so the hook's own `retry` option (under test)
    // drives the call count without slowing the suite.
    defaultOptions: { queries: { retryDelay: 0 } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return renderHook(() => useAgentFleetApprovals(), { wrapper });
}

describe("useAgentFleetApprovals", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("flags a 404 as a permission error without retrying", async () => {
    mockListAgentFleetApprovals.mockRejectedValue(
      new ApiRequestError(404, '{"detail":"Not found"}'),
    );
    const { result } = renderApprovalsHook();

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.isPermissionError).toBe(true);
    // The admin gate never clears on retry, so the hook must not retry.
    expect(mockListAgentFleetApprovals).toHaveBeenCalledTimes(1);
  });

  it("treats non-404 failures as genuine errors and retries them", async () => {
    mockListAgentFleetApprovals.mockRejectedValue(
      new ApiRequestError(500, '{"error":"boom"}'),
    );
    const { result } = renderApprovalsHook();

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.isPermissionError).toBe(false);
    expect(mockListAgentFleetApprovals).toHaveBeenCalledTimes(4);
  });

  it("returns approvals on success", async () => {
    mockListAgentFleetApprovals.mockResolvedValue([{ id: "approval-1" }]);
    const { result } = renderApprovalsHook();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([{ id: "approval-1" }]);
    expect(result.current.isPermissionError).toBe(false);
  });
});

describe("isApprovalsPermissionError", () => {
  it.each([
    [new ApiRequestError(404, "{}"), true],
    [new ApiRequestError(500, "{}"), false],
    [new Error("Failed request: [404] {}"), false],
    [null, false],
  ])("maps %s to %s", (error, expected) => {
    expect(isApprovalsPermissionError(error)).toBe(expected);
  });
});
