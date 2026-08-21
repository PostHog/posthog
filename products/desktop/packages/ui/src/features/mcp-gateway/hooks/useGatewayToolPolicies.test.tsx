import type { McpResolvedToolPolicy } from "@posthog/api-client/posthog-client";
import {
  gatewayKeys,
  TEAM_SCOPE,
  YOU_SCOPE,
} from "@posthog/ui/features/mcp-gateway/hooks/gatewayKeys";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getPolicies: vi.fn(),
  upsertPolicies: vi.fn(),
  refreshTools: vi.fn(),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({
    getMcpGatewayToolPolicies: mocks.getPolicies,
    upsertMcpGatewayToolPolicies: mocks.upsertPolicies,
    refreshMcpInstallationTools: mocks.refreshTools,
  }),
}));

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: vi.fn() },
}));

import { toast } from "@posthog/ui/primitives/toast";

import {
  resetGatewayToolAutoDiscovery,
  useGatewayToolPolicies,
} from "./useGatewayToolPolicies";

const serverId = "server-1";

function policy(policyState: "needs_approval" | "approved") {
  return {
    tool_name: "search",
    description: "Search for things",
    input_schema: {},
    policy_state: policyState,
    team_state: policyState,
    locked: false,
    decided_by: "team",
    rule_name: "",
    rule_description: "",
  } satisfies McpResolvedToolPolicy;
}

let queryClient: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useGatewayToolPolicies", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetGatewayToolAutoDiscovery();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  it("keeps the mutation result visible while invalidating inherited scopes", async () => {
    const stalePolicies = [policy("needs_approval")];
    const updatedPolicies = [policy("approved")];
    mocks.getPolicies.mockResolvedValue(stalePolicies);
    mocks.upsertPolicies.mockResolvedValue(updatedPolicies);

    const { result } = renderHook(
      () => useGatewayToolPolicies(serverId, TEAM_SCOPE),
      { wrapper },
    );

    await waitFor(() => expect(result.current.policies).toEqual(stalePolicies));

    const memberKey = gatewayKeys.tools(serverId, YOU_SCOPE);
    queryClient.setQueryData(memberKey, stalePolicies);

    act(() => {
      result.current.setPolicy({ toolName: "search", state: "approved" });
    });

    await waitFor(() =>
      expect(result.current.policies).toEqual(updatedPolicies),
    );
    await act(async () => {
      await Promise.resolve();
    });

    expect(mocks.getPolicies).toHaveBeenCalledTimes(1);
    expect(
      queryClient.getQueryData(gatewayKeys.tools(serverId, TEAM_SCOPE)),
    ).toEqual(updatedPolicies);
    expect(queryClient.getQueryState(memberKey)?.isInvalidated).toBe(true);
    expect(
      queryClient.getQueryState(gatewayKeys.tools(serverId, TEAM_SCOPE))
        ?.isInvalidated,
    ).toBe(false);
  });

  describe("auto-discovery", () => {
    it("lists tools once when the catalog resolves empty", async () => {
      mocks.getPolicies.mockResolvedValue([]);
      mocks.refreshTools.mockResolvedValue([]);

      const { result, rerender } = renderHook(
        () =>
          useGatewayToolPolicies(serverId, YOU_SCOPE, {
            autoDiscoverWith: "inst-1",
          }),
        { wrapper },
      );

      await waitFor(() =>
        expect(mocks.refreshTools).toHaveBeenCalledWith("inst-1"),
      );
      await waitFor(() => expect(result.current.refreshPending).toBe(false));

      rerender();
      expect(mocks.refreshTools).toHaveBeenCalledTimes(1);
    });

    it.each([
      ["the catalog already has tools", [policy("approved")], "inst-1"],
      ["there is no live connection", [], null],
    ])("stays put when %s", async (_label, policies, installationId) => {
      mocks.getPolicies.mockResolvedValue(policies);

      const { result } = renderHook(
        () =>
          useGatewayToolPolicies(serverId, YOU_SCOPE, {
            autoDiscoverWith: installationId,
          }),
        { wrapper },
      );

      await waitFor(() => expect(result.current.policiesLoading).toBe(false));
      await act(async () => {
        await Promise.resolve();
      });

      expect(mocks.refreshTools).not.toHaveBeenCalled();
    });

    it("retries on a later mount when the listing fails", async () => {
      mocks.getPolicies.mockResolvedValue([]);
      mocks.refreshTools.mockRejectedValue(new Error("upstream down"));

      const first = renderHook(
        () =>
          useGatewayToolPolicies(serverId, YOU_SCOPE, {
            autoDiscoverWith: "inst-1",
          }),
        { wrapper },
      );
      await waitFor(() => expect(mocks.refreshTools).toHaveBeenCalledTimes(1));
      await waitFor(() =>
        expect(first.result.current.refreshPending).toBe(false),
      );
      first.unmount();

      renderHook(
        () =>
          useGatewayToolPolicies(serverId, YOU_SCOPE, {
            autoDiscoverWith: "inst-1",
          }),
        { wrapper },
      );

      await waitFor(() => expect(mocks.refreshTools).toHaveBeenCalledTimes(2));
      expect(toast.error).not.toHaveBeenCalled();
    });
  });
});
