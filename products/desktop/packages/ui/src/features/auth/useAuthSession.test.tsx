import { USAGE_QUERY_KEY } from "@posthog/ui/features/billing/useUsage";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useUsageIdentitySync } from "./useAuthSession";

let queryClient: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useUsageIdentitySync", () => {
  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  it("drops the cached usage snapshot on mount", () => {
    const removeSpy = vi.spyOn(queryClient, "removeQueries");

    renderHook(() => useUsageIdentitySync("us:none", "org-a"), { wrapper });

    expect(removeSpy).toHaveBeenCalledWith({ queryKey: USAGE_QUERY_KEY });
    expect(removeSpy).toHaveBeenCalledTimes(1);
  });

  it("re-clears the snapshot when the org changes even if authIdentity is unchanged", () => {
    // Regression: usage is org-scoped, but authIdentity keys on region + project.
    // Switching between two orgs that both have no selected project leaves
    // authIdentity at "region:none", so keying only on it would leave the
    // previous org's spend cached after a failed refresh.
    const removeSpy = vi.spyOn(queryClient, "removeQueries");

    const { rerender } = renderHook(
      ({ authIdentity, orgId }) => useUsageIdentitySync(authIdentity, orgId),
      { wrapper, initialProps: { authIdentity: "us:none", orgId: "org-a" } },
    );
    removeSpy.mockClear();

    rerender({ authIdentity: "us:none", orgId: "org-b" });

    expect(removeSpy).toHaveBeenCalledWith({ queryKey: USAGE_QUERY_KEY });
    expect(removeSpy).toHaveBeenCalledTimes(1);
  });

  it("re-clears the snapshot when authIdentity changes", () => {
    const removeSpy = vi.spyOn(queryClient, "removeQueries");

    const { rerender } = renderHook(
      ({ authIdentity, orgId }) => useUsageIdentitySync(authIdentity, orgId),
      { wrapper, initialProps: { authIdentity: "us:1", orgId: "org-a" } },
    );
    removeSpy.mockClear();

    rerender({ authIdentity: "us:2", orgId: "org-a" });

    expect(removeSpy).toHaveBeenCalledTimes(1);
  });

  it("does not re-clear when neither authIdentity nor org changes", () => {
    const removeSpy = vi.spyOn(queryClient, "removeQueries");

    const { rerender } = renderHook(
      ({ authIdentity, orgId }) => useUsageIdentitySync(authIdentity, orgId),
      { wrapper, initialProps: { authIdentity: "us:1", orgId: "org-a" } },
    );
    removeSpy.mockClear();

    rerender({ authIdentity: "us:1", orgId: "org-a" });

    expect(removeSpy).not.toHaveBeenCalled();
  });
});
