import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

const { auth, client } = vi.hoisted(() => ({
  auth: { identity: "us:1" as string | null },
  client: {
    getClaudeUserIntegration: vi.fn(async () => ({
      status: "connected",
      connected_at: null,
      expires_at: null,
    })),
    getCodexUserIntegration: vi.fn(async () => ({
      status: "connected",
      plan_type: null,
      email: null,
      connected_at: null,
    })),
  },
}));

vi.mock("@posthog/ui/features/auth/store", () => ({
  getAuthIdentity: () => auth.identity,
  useAuthStateValue: (selector: (state: unknown) => unknown) =>
    selector(undefined),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => client,
}));

import { useClaudeCloudAccount } from "./claudeCloudAccount";
import { useCodexCloudAccount } from "./codexCloudAccount";

describe("cloud account status queries", () => {
  it.each([
    ["claude-cloud-account", useClaudeCloudAccount],
    ["codex-cloud-account", useCodexCloudAccount],
  ] as const)(
    "keeps %s apart per PostHog account and drops it on logout",
    async (prefix, useAccount) => {
      const queryClient = new QueryClient();
      const wrapper = ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={queryClient}>
          {children}
        </QueryClientProvider>
      );
      auth.identity = "us:1";
      const { result, rerender } = renderHook(() => useAccount(), { wrapper });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      auth.identity = "eu:2";
      rerender();
      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      const queries = queryClient
        .getQueryCache()
        .findAll({ queryKey: [prefix] });
      expect(queries.map((query) => query.queryKey)).toEqual([
        [prefix, "us:1"],
        [prefix, "eu:2"],
      ]);

      queryClient.removeQueries({
        predicate: (query) => query.meta?.authScoped === true,
      });
      expect(
        queryClient.getQueryCache().findAll({ queryKey: [prefix] }),
      ).toEqual([]);
    },
  );
});
