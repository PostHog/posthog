import { ApiRequestError } from "@posthog/api-client/fetcher";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockListAgentApplicationApprovals = vi.hoisted(() => vi.fn());
const mockClient = vi.hoisted(() => ({
  listAgentApplicationApprovals: mockListAgentApplicationApprovals,
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => mockClient,
}));

vi.mock("../../auth/store", () => ({
  useAuthStateValue: <T,>(
    selector: (state: { currentProjectId: number }) => T,
  ) => selector({ currentProjectId: 2 }),
}));

import { useAgentApplicationApprovals } from "./useAgentApplicationApprovals";

function renderApprovalsHook(idOrSlug: string) {
  const queryClient = new QueryClient({
    // Zero out the backoff so the hook's own `retry` option (under test)
    // drives the call count without slowing the suite.
    defaultOptions: { queries: { retryDelay: 0 } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return renderHook(() => useAgentApplicationApprovals(idOrSlug), { wrapper });
}

describe("useAgentApplicationApprovals", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("flags a 404 as a permission error without retrying", async () => {
    mockListAgentApplicationApprovals.mockRejectedValue(
      new ApiRequestError(404, '{"detail":"Not found"}'),
    );
    const { result } = renderApprovalsHook("my-agent");

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.isPermissionError).toBe(true);
    // The admin gate never clears on retry, so the hook must not retry.
    expect(mockListAgentApplicationApprovals).toHaveBeenCalledTimes(1);
  });

  it("treats non-404 failures as genuine errors and retries them", async () => {
    mockListAgentApplicationApprovals.mockRejectedValue(
      new ApiRequestError(500, '{"error":"boom"}'),
    );
    const { result } = renderApprovalsHook("my-agent");

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.isPermissionError).toBe(false);
    expect(mockListAgentApplicationApprovals).toHaveBeenCalledTimes(4);
  });

  it("returns approvals on success", async () => {
    mockListAgentApplicationApprovals.mockResolvedValue([{ id: "approval-1" }]);
    const { result } = renderApprovalsHook("my-agent");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([{ id: "approval-1" }]);
    expect(result.current.isPermissionError).toBe(false);
  });

  it("stays disabled and never fetches without an idOrSlug", async () => {
    mockListAgentApplicationApprovals.mockResolvedValue([]);
    const { result } = renderApprovalsHook("");

    // enabled gates on !!idOrSlug — the query must stay pending with no fetch.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(mockListAgentApplicationApprovals).not.toHaveBeenCalled();
    expect(result.current.isPending).toBe(true);
    expect(result.current.isPermissionError).toBe(false);
  });
});
