import type { AgentPluginsClient } from "@posthog/core/agent-plugins/agentPluginsClient";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

const mockClient = vi.hoisted<AgentPluginsClient>(() => ({
  list: vi.fn(),
  select: vi.fn(),
  register: vi.fn(),
  setEnabled: vi.fn(),
  approveStdio: vi.fn(),
  unregister: vi.fn(),
}));

vi.mock("@posthog/di/react", () => ({
  useService: () => mockClient,
}));

import { useSetAgentPluginEnabled } from "./useAgentPlugins";

function deferred(): {
  promise: Promise<void>;
  resolve: () => void;
} {
  let resolve = (): void => {};
  const promise = new Promise<void>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

describe("useAgentPlugins", () => {
  it("keeps a mutation pending until the installed list is refreshed", async () => {
    const refresh = deferred();
    const queryClient = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    });
    vi.spyOn(queryClient, "invalidateQueries").mockReturnValue(refresh.promise);
    vi.mocked(mockClient.setEnabled).mockResolvedValue({
      id: "0123456789abcdef",
      sourcePath: "/plugins/example",
      enabled: false,
      manifest: { $schema: "schema", name: "example" },
      skills: [],
      mcpServers: [],
      diagnostics: [],
      stdioApprovalRequired: false,
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useSetAgentPluginEnabled(), {
      wrapper,
    });

    let mutation!: Promise<unknown>;
    await act(async () => {
      mutation = result.current.mutateAsync({
        id: "0123456789abcdef",
        enabled: false,
      });
      await Promise.resolve();
    });

    await waitFor(() => expect(result.current.isPending).toBe(true));
    expect(queryClient.invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["agent-plugins"],
    });

    refresh.resolve();
    await act(async () => {
      await mutation;
    });
    await waitFor(() => expect(result.current.isPending).toBe(false));
  });
});
