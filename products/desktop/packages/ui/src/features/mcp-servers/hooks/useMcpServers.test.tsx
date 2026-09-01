import type { McpRecommendedServer } from "@posthog/api-client/posthog-client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockClient = vi.hoisted(() => ({
  getMcpServerInstallations: vi.fn(),
  getMcpServers: vi.fn(),
  installMcpTemplate: vi.fn(),
  installCustomMcpServer: vi.fn(),
  uninstallMcpServer: vi.fn(),
  updateMcpServerInstallation: vi.fn(),
  authorizeMcpInstallation: vi.fn(),
}));

const mockTrpcClient = vi.hoisted(() => ({
  mcpCallback: {
    getCallbackUrl: { query: vi.fn() },
    openAndWaitForCallback: { mutate: vi.fn() },
  },
}));

const mockTrpc = vi.hoisted(() => ({
  mcpCallback: {
    onOAuthComplete: {
      subscriptionOptions: vi.fn(() => ({})),
    },
  },
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => mockClient,
}));

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => mockTrpc,
  useHostTRPCClient: () => mockTrpcClient,
}));

vi.mock("@trpc/tanstack-react-query", () => ({
  useSubscription: vi.fn(),
}));

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

import { useMcpServers } from "./useMcpServers";

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

const template = {
  id: "granola",
  name: "Granola",
  auth_type: "oauth",
} as McpRecommendedServer;

describe("useMcpServers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockClient.getMcpServerInstallations.mockResolvedValue([]);
    mockClient.getMcpServers.mockResolvedValue([]);
    mockTrpcClient.mcpCallback.getCallbackUrl.query.mockResolvedValue({
      callbackUrl: "posthog-code://mcp-oauth-complete",
    });
  });

  it("reverts template connect loading state after a failed install", async () => {
    let rejectInstall!: (error: Error) => void;
    mockClient.installMcpTemplate.mockReturnValue(
      new Promise((_resolve, reject) => {
        rejectInstall = reject;
      }),
    );

    const { result } = renderHook(() => useMcpServers(), { wrapper });

    act(() => {
      result.current.installTemplate(template);
    });

    await waitFor(() => expect(result.current.installingId).toBe("granola"));
    await waitFor(() =>
      expect(mockClient.installMcpTemplate).toHaveBeenCalledWith({
        template_id: "granola",
        install_source: "posthog-code",
        posthog_code_callback_url: "posthog-code://mcp-oauth-complete",
        api_key: undefined,
      }),
    );

    await act(async () => {
      rejectInstall(new Error("Connection failed"));
    });

    await waitFor(() => expect(result.current.installingId).toBeNull());
  });
});
