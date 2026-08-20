import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiClient = vi.hoisted(() => ({ setTaskArchived: vi.fn() }));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => apiClient,
}));

const archivedIds = vi.hoisted(() => ({ current: new Set<string>() }));

vi.mock("@posthog/ui/features/archive/useArchivedTaskIds", () => ({
  useArchivedTaskIds: () => archivedIds.current,
}));

import { useServerArchiveSyncStore } from "./serverArchiveSyncStore";
import { useServerArchiveSync } from "./useServerArchiveSync";

let queryClient: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useServerArchiveSync", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    archivedIds.current = new Set();
    useServerArchiveSyncStore.setState({
      syncedTaskIds: [],
      pendingUnarchiveTaskIds: [],
    });
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  it("mirrors a locally archived task the server has not been told about", async () => {
    apiClient.setTaskArchived.mockResolvedValue(undefined);
    archivedIds.current = new Set(["t1"]);

    renderHook(() => useServerArchiveSync(), { wrapper });

    await waitFor(() =>
      expect(apiClient.setTaskArchived).toHaveBeenCalledWith("t1", true),
    );
    expect(useServerArchiveSyncStore.getState().syncedTaskIds).toContain("t1");
  });

  it("syncs a task archived after the drain's last read, before the drain ended", async () => {
    // Regression: the trigger for a task archived mid-drain hit the `running`
    // guard and returned, and nothing re-fired once the drain finished, so the
    // task stayed server-visible until an unrelated trigger or a relaunch.
    let releaseFirstPatch: () => void = () => {};
    const firstPatchStarted = new Promise<void>((patchCalled) => {
      apiClient.setTaskArchived.mockImplementationOnce(
        () =>
          new Promise<void>((resolve) => {
            releaseFirstPatch = resolve;
            patchCalled();
          }),
      );
    });
    apiClient.setTaskArchived.mockResolvedValue(undefined);
    archivedIds.current = new Set(["t1"]);

    const { rerender } = renderHook(() => useServerArchiveSync(), { wrapper });
    await firstPatchStarted;

    // A second task is archived while the first PATCH is still in flight.
    archivedIds.current = new Set(["t1", "t2"]);
    await act(async () => {
      rerender();
      releaseFirstPatch();
    });

    await waitFor(() =>
      expect(apiClient.setTaskArchived).toHaveBeenCalledWith("t2", true),
    );
  });

  it("leaves a task the server refused out of syncedTaskIds so a later pass retries it", async () => {
    apiClient.setTaskArchived.mockRejectedValue(new Error("nope"));
    archivedIds.current = new Set(["t1"]);

    renderHook(() => useServerArchiveSync(), { wrapper });

    await waitFor(() =>
      expect(apiClient.setTaskArchived).toHaveBeenCalledWith("t1", true),
    );
    expect(useServerArchiveSyncStore.getState().syncedTaskIds).not.toContain(
      "t1",
    );
  });

  it("clears a queued restore on the server and drops it from the mirrored record", async () => {
    apiClient.setTaskArchived.mockResolvedValue(undefined);
    useServerArchiveSyncStore.setState({
      syncedTaskIds: ["t1"],
      pendingUnarchiveTaskIds: ["t1"],
    });

    renderHook(() => useServerArchiveSync(), { wrapper });

    await waitFor(() =>
      expect(apiClient.setTaskArchived).toHaveBeenCalledWith("t1", false),
    );
    const state = useServerArchiveSyncStore.getState();
    expect(state.pendingUnarchiveTaskIds).not.toContain("t1");
    expect(state.syncedTaskIds).not.toContain("t1");
  });
});
