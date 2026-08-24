import type { DetectedApplication } from "@posthog/shared/domain-types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockClient = vi.hoisted(() => ({
  externalApps: {
    getDetectedApps: { query: vi.fn() },
    getLastUsed: { query: vi.fn() },
    setLastUsed: { mutate: vi.fn() },
  },
}));
vi.mock("@posthog/host-router/react", () => ({
  useHostTRPCClient: () => mockClient,
}));

import { useExternalApps } from "./useExternalApps";

const apps = [
  { id: "vscode", name: "VS Code" },
  { id: "cursor", name: "Cursor" },
] as unknown as DetectedApplication[];

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useExternalApps", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockClient.externalApps.getDetectedApps.query.mockResolvedValue(apps);
    mockClient.externalApps.getLastUsed.query.mockResolvedValue({
      lastUsedApp: undefined,
    });
    mockClient.externalApps.setLastUsed.mutate.mockResolvedValue(undefined);
  });

  it("defaults to the first detected app when none was last used", async () => {
    const { result } = renderHook(() => useExternalApps(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.detectedApps).toEqual(apps);
    expect(result.current.defaultApp?.id).toBe("vscode");
  });

  it("prefers the last-used app as the default", async () => {
    mockClient.externalApps.getLastUsed.query.mockResolvedValue({
      lastUsedApp: "cursor",
    });
    const { result } = renderHook(() => useExternalApps(), { wrapper });
    await waitFor(() => expect(result.current.lastUsedAppId).toBe("cursor"));
    expect(result.current.defaultApp?.id).toBe("cursor");
  });

  it("setLastUsedApp forwards to the client", async () => {
    const { result } = renderHook(() => useExternalApps(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    await act(async () => {
      await result.current.setLastUsedApp("cursor");
    });
    expect(mockClient.externalApps.setLastUsed.mutate).toHaveBeenCalledWith({
      appId: "cursor",
    });
  });
});
