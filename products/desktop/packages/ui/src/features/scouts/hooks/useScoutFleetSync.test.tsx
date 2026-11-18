import { ScoutRequestError } from "@posthog/api-client/posthog-client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const syncScoutConfigs = vi.hoisted(() => vi.fn());

vi.mock("@posthog/ui/features/auth/store", () => ({
  useAuthStateValue: (
    select: (state: { currentProjectId: number | null }) => unknown,
  ) => select({ currentProjectId: 42 }),
}));
vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({ syncScoutConfigs }),
}));
vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  AUTH_SCOPED_QUERY_META: {},
}));

import { useScoutFleetSync } from "./useScoutFleetSync";

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useScoutFleetSync", () => {
  beforeEach(() => {
    syncScoutConfigs.mockReset();
  });

  // A refused sync leaves the section on whatever the list query returned, so an empty fleet
  // from a viewer who cannot write looks exactly like a project that has no scouts. The
  // outcome is what tells those apart on `Scout fleet viewed`.
  it.each([
    ["a fleet", "synced", null],
    [
      "403",
      "skipped_permission",
      new ScoutRequestError(403, "configs/sync/", "Forbidden"),
    ],
    [
      "404",
      "not_found",
      new ScoutRequestError(404, "configs/sync/", "Not Found"),
    ],
    [
      "500",
      "failed",
      new ScoutRequestError(500, "configs/sync/", "Server Error"),
    ],
    ["a network drop", "failed", new Error("offline")],
  ])("reports %s as %s", async (_label, expected, error) => {
    if (error) {
      syncScoutConfigs.mockRejectedValue(error);
    } else {
      syncScoutConfigs.mockResolvedValue([]);
    }

    const { result } = renderHook(() => useScoutFleetSync(), { wrapper });

    await waitFor(() => expect(result.current.isSyncing).toBe(false));
    expect(result.current.syncOutcome).toBe(expected);
  });
});
