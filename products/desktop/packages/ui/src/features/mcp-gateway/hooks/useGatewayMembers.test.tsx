import type {
  McpGatewayMemberSummary,
  McpGatewayServer,
} from "@posthog/api-client/posthog-client";
import { gatewayKeys } from "@posthog/ui/features/mcp-gateway/hooks/gatewayKeys";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getMembers: vi.fn(),
  setMemberAccess: vi.fn(),
  successToast: vi.fn(),
  infoToast: vi.fn(),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({
    getMcpGatewayMembers: mocks.getMembers,
    setMcpGatewayMemberAccess: mocks.setMemberAccess,
  }),
}));

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: {
    error: vi.fn(),
    success: mocks.successToast,
    info: mocks.infoToast,
  },
}));

import { useGatewayMembers } from "./useGatewayMembers";

const member = {
  user: {
    id: 7,
    uuid: "user-7",
    first_name: "Ada",
    last_name: "Lovelace",
    email: "ada@example.com",
    hedgehog_config: null,
  },
  is_org_admin: false,
  connected_server_ids: ["server-1"],
  revoked_server_ids: [],
} as McpGatewayMemberSummary;

const server = {
  id: "server-1",
  revoked_user_ids: [],
} as unknown as McpGatewayServer;

let queryClient: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useGatewayMembers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mocks.getMembers.mockResolvedValue([member]);
    mocks.setMemberAccess.mockResolvedValue(undefined);
  });

  it("updates member and server access caches without a stale refetch", async () => {
    queryClient.setQueryData(gatewayKeys.servers, [server]);
    const { result } = renderHook(() => useGatewayMembers({ enabled: true }), {
      wrapper,
    });

    await waitFor(() => expect(result.current.members).toEqual([member]));

    act(() => {
      result.current.setMemberAccess({
        userId: member.user.id,
        serverId: server.id,
        enabled: false,
        successMessage: "Ada can no longer use Linear",
      });
    });

    await waitFor(() =>
      expect(result.current.members[0]?.revoked_server_ids).toEqual([
        server.id,
      ]),
    );

    expect(
      queryClient.getQueryData<McpGatewayServer[]>(gatewayKeys.servers)?.[0]
        ?.revoked_user_ids,
    ).toEqual([member.user.id]);
    expect(mocks.getMembers).toHaveBeenCalledTimes(1);
    expect(mocks.infoToast).toHaveBeenCalledWith(
      "Ada can no longer use Linear",
    );

    act(() => {
      result.current.setMemberAccess({
        userId: member.user.id,
        serverId: server.id,
        enabled: true,
        successMessage: "Ada can now use Linear",
      });
    });

    await waitFor(() =>
      expect(result.current.members[0]?.revoked_server_ids).toEqual([]),
    );

    expect(
      queryClient.getQueryData<McpGatewayServer[]>(gatewayKeys.servers)?.[0]
        ?.revoked_user_ids,
    ).toEqual([]);
    expect(mocks.getMembers).toHaveBeenCalledTimes(1);
    expect(mocks.successToast).toHaveBeenCalledWith("Ada can now use Linear");
  });
});
