import type { LocalMcpCloudClassification } from "@posthog/core/local-mcp/localMcpImport";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  flagEnabled: false,
  getCloudAvailability: vi.fn(),
}));

vi.mock("@posthog/di/react", () => ({
  useServiceOptional: () => ({
    getCloudAvailability: mocks.getCloudAvailability,
  }),
}));

vi.mock("../feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => mocks.flagEnabled,
}));

import { useLocalMcpCloudServers } from "./useLocalMcpCloudServers";

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

const server: LocalMcpCloudClassification = {
  name: "internal-tools",
  availability: "requires_desktop",
  reason: "stdio_transport",
};

describe("useLocalMcpCloudServers", () => {
  beforeEach(() => {
    mocks.flagEnabled = false;
    mocks.getCloudAvailability.mockReset();
    mocks.getCloudAvailability.mockResolvedValue([server]);
  });

  it("does not inspect local MCP servers while the feature flag is disabled", () => {
    const { result } = renderHook(() => useLocalMcpCloudServers(true), {
      wrapper,
    });

    expect(result.current).toEqual({ servers: [], isLoading: false });
    expect(mocks.getCloudAvailability).not.toHaveBeenCalled();
  });

  it("returns local MCP servers while the feature flag is enabled", async () => {
    mocks.flagEnabled = true;

    const { result } = renderHook(() => useLocalMcpCloudServers(true), {
      wrapper,
    });

    await waitFor(() =>
      expect(result.current).toEqual({ servers: [server], isLoading: false }),
    );
  });

  it("hides cached local MCP servers when the feature flag is disabled", async () => {
    mocks.flagEnabled = true;
    const { result, rerender } = renderHook(
      () => useLocalMcpCloudServers(true),
      { wrapper },
    );
    await waitFor(() => expect(result.current.servers).toEqual([server]));

    mocks.flagEnabled = false;
    rerender();

    expect(result.current).toEqual({ servers: [], isLoading: false });
  });
});
