import type { McpInstallationTool } from "@posthog/api-client/posthog-client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockClient = vi.hoisted(() => ({
  getMcpInstallationTools: vi.fn(),
  updateMcpToolApproval: vi.fn(),
  refreshMcpInstallationTools: vi.fn(),
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

// Keep the real retry budget but collapse the backoff so the tests stay fast.
vi.mock("@posthog/core/mcp-servers/toolRefresh", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@posthog/core/mcp-servers/toolRefresh")
  >()),
  autoRefreshRetryDelayMs: () => 5,
}));

import { toast } from "@posthog/ui/primitives/toast";

import { useMcpInstallationTools } from "./useMcpInstallationTools";

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

function makeTool(
  overrides: Partial<McpInstallationTool> & { tool_name: string },
): McpInstallationTool {
  return {
    id: overrides.tool_name,
    display_name: overrides.tool_name,
    description: "",
    input_schema: {},
    approval_state: "approved",
    last_seen_at: "2026-01-01T00:00:00Z",
    removed_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

describe("useMcpInstallationTools setBulkApproval", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockClient.updateMcpToolApproval.mockResolvedValue({});
  });

  it("excludes rule-locked tools from bulk writes even in team scope", async () => {
    mockClient.getMcpInstallationTools.mockResolvedValue([
      makeTool({ tool_name: "unlocked" }),
      makeTool({ tool_name: "rule-locked", locked: true }),
    ]);

    const { result } = renderHook(
      () => useMcpInstallationTools("inst-1", { teamScope: true }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.tools).toHaveLength(2));

    act(() => result.current.setBulkApproval("do_not_use"));

    await waitFor(() =>
      expect(mockClient.updateMcpToolApproval).toHaveBeenCalledTimes(1),
    );
    expect(mockClient.updateMcpToolApproval).toHaveBeenCalledWith(
      "inst-1",
      "unlocked",
      "do_not_use",
    );
  });

  it("skips the team ceiling in team scope, since team scope sets it", async () => {
    mockClient.getMcpInstallationTools.mockResolvedValue([
      makeTool({ tool_name: "restricted", team_state: "do_not_use" }),
    ]);

    const { result } = renderHook(
      () => useMcpInstallationTools("inst-1", { teamScope: true }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.tools).toHaveLength(1));

    act(() => result.current.setBulkApproval("approved"));

    await waitFor(() =>
      expect(mockClient.updateMcpToolApproval).toHaveBeenCalledWith(
        "inst-1",
        "restricted",
        "approved",
      ),
    );
  });

  it("excludes locked tools and tools above the team ceiling in member scope", async () => {
    mockClient.getMcpInstallationTools.mockResolvedValue([
      makeTool({ tool_name: "unlocked" }),
      makeTool({ tool_name: "rule-locked", locked: true }),
      makeTool({ tool_name: "restricted", team_state: "do_not_use" }),
    ]);

    const { result } = renderHook(() => useMcpInstallationTools("inst-1"), {
      wrapper,
    });
    await waitFor(() => expect(result.current.tools).toHaveLength(3));

    act(() => result.current.setBulkApproval("approved"));

    await waitFor(() =>
      expect(mockClient.updateMcpToolApproval).toHaveBeenCalledTimes(1),
    );
    expect(mockClient.updateMcpToolApproval).toHaveBeenCalledWith(
      "inst-1",
      "unlocked",
      "approved",
    );
  });
});

describe("useMcpInstallationTools auto-refresh", () => {
  let queryClient: QueryClient;

  function stableWrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  }

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
  });

  it("retries a failed silent refresh a bounded number of times, then stops until a later mount", async () => {
    mockClient.getMcpInstallationTools.mockResolvedValue([]);
    // Reject on a later tick so the pending state renders first, as a real
    // request does. An immediate rejection collapses the pending and error
    // renders into one and hides the re-fire this guards against.
    mockClient.refreshMcpInstallationTools.mockImplementation(
      () =>
        new Promise((_resolve, reject) =>
          setTimeout(() => reject(new Error("upstream down")), 5),
        ),
    );

    const first = renderHook(
      () =>
        useMcpInstallationTools("inst-auto-refresh", {
          autoRefreshIfEmpty: true,
        }),
      { wrapper: stableWrapper },
    );
    // One attempt plus AUTO_REFRESH_MAX_RETRIES retries.
    await waitFor(() =>
      expect(mockClient.refreshMcpInstallationTools).toHaveBeenCalledTimes(3),
    );
    // Long enough for the last failure to settle and re-run the auto-refresh
    // effect; a fourth listing here is the retry storm this guards against.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 60));
    });
    expect(first.result.current.refreshPending).toBe(false);
    expect(mockClient.refreshMcpInstallationTools).toHaveBeenCalledTimes(3);
    expect(toast.error).not.toHaveBeenCalled();
    first.unmount();

    renderHook(
      () =>
        useMcpInstallationTools("inst-auto-refresh", {
          autoRefreshIfEmpty: true,
        }),
      { wrapper: stableWrapper },
    );
    // A later mount gets one more bounded batch, not an open-ended one.
    await waitFor(() =>
      expect(mockClient.refreshMcpInstallationTools).toHaveBeenCalledTimes(6),
    );
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 60));
    });
    expect(mockClient.refreshMcpInstallationTools).toHaveBeenCalledTimes(6);
  });
});
