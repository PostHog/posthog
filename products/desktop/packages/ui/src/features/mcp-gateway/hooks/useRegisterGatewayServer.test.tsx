import type { GatewayInstallRequest } from "@posthog/core/mcp-gateway/gatewayAddServer";
import {
  gatewayKeys,
  YOU_SCOPE,
} from "@posthog/ui/features/mcp-gateway/hooks/gatewayKeys";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  installCustom: vi.fn(),
  getServers: vi.fn(),
  refreshTools: vi.fn(),
  getCallbackUrl: vi.fn(),
  openAndWait: vi.fn(),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({
    installCustomMcpServer: mocks.installCustom,
    getMcpGatewayServers: mocks.getServers,
    refreshMcpInstallationTools: mocks.refreshTools,
  }),
}));

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPCClient: () => ({
    mcpCallback: {
      getCallbackUrl: { query: mocks.getCallbackUrl },
      openAndWaitForCallback: { mutate: mocks.openAndWait },
    },
  }),
}));

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import { useRegisterGatewayServer } from "./useRegisterGatewayServer";

const request: GatewayInstallRequest = {
  name: "Linear",
  url: "https://mcp.linear.app/sse",
  description: "",
  auth_type: "oauth",
};

function gatewayServer(overrides: Record<string, unknown> = {}) {
  return {
    id: "srv-1",
    name: "Linear",
    url: "https://mcp.linear.app/sse",
    description: "",
    category: "dev",
    is_team_enabled: true,
    icon_key: "",
    docs_url: "",
    template_id: null,
    template_auth_type: null,
    tool_count: 0,
    connections: [],
    your_connection: {
      installation_id: "inst-1",
      is_enabled: true,
      pending_oauth: false,
      needs_reauth: false,
      last_used_at: null,
    },
    agents: [],
    revoked_user_ids: [],
    is_revoked_for_you: false,
    created_by: null,
    created_at: "2026-07-30T00:00:00Z",
    updated_at: "2026-07-30T00:00:00Z",
    ...overrides,
  };
}

let queryClient: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useRegisterGatewayServer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mocks.getCallbackUrl.mockResolvedValue({ callbackUrl: "posthog://cb" });
    mocks.openAndWait.mockResolvedValue({ success: true });
    mocks.installCustom.mockResolvedValue({ redirect_url: "https://oauth" });
    mocks.refreshTools.mockResolvedValue([]);
  });

  async function register() {
    const { result } = renderHook(() => useRegisterGatewayServer(), {
      wrapper,
    });
    let outcome: { created: unknown; discoveredTools: boolean } | null = null;
    act(() => {
      result.current.register(
        { request },
        {
          onSuccess: (data) => {
            outcome = data;
          },
        },
      );
    });
    await waitFor(() => expect(outcome).not.toBeNull());
    return outcome as unknown as {
      created: { id: string } | null;
      discoveredTools: boolean;
    };
  }

  it("lists the new server's tools so the detail page isn't empty", async () => {
    mocks.getServers.mockResolvedValue([gatewayServer()]);
    const toolsKey = gatewayKeys.tools("srv-1", YOU_SCOPE);
    queryClient.setQueryData(toolsKey, []);

    const outcome = await register();

    expect(mocks.refreshTools).toHaveBeenCalledWith("inst-1");
    expect(outcome.discoveredTools).toBe(true);
    // The detail page's catalog query must re-read what the listing stored.
    expect(queryClient.getQueryState(toolsKey)?.isInvalidated).toBe(true);
  });

  it("still registers the server when the tool listing fails", async () => {
    mocks.getServers.mockResolvedValue([gatewayServer()]);
    mocks.refreshTools.mockRejectedValue(new Error("upstream down"));

    const outcome = await register();

    expect(outcome.created?.id).toBe("srv-1");
    expect(outcome.discoveredTools).toBe(false);
  });

  it("skips the listing when the credential is still mid-OAuth", async () => {
    mocks.getServers.mockResolvedValue([
      gatewayServer({
        your_connection: {
          installation_id: "inst-1",
          is_enabled: true,
          pending_oauth: true,
          needs_reauth: false,
          last_used_at: null,
        },
      }),
    ]);

    const outcome = await register();

    expect(mocks.refreshTools).not.toHaveBeenCalled();
    expect(outcome.created?.id).toBe("srv-1");
  });
});
