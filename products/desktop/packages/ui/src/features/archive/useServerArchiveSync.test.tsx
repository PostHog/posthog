import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiClient = vi.hoisted(() => ({
  getTasksWithStatus: vi.fn(),
  setTaskArchived: vi.fn(),
}));
const archiveLocally = vi.hoisted(() => vi.fn());
const refreshArchiveState = vi.hoisted(() => vi.fn());

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => apiClient,
}));

vi.mock("@posthog/di/react", () => ({
  useService: () => ({
    archive: archiveLocally,
    refreshArchiveState,
  }),
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
    apiClient.getTasksWithStatus.mockResolvedValue({
      tasks: [],
      isComplete: true,
    });
    archiveLocally.mockResolvedValue(undefined);
    refreshArchiveState.mockResolvedValue(undefined);
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

  it("imports a task archived on the server into the local archive", async () => {
    apiClient.getTasksWithStatus.mockResolvedValue({
      tasks: [
        {
          id: "t1",
          title: "Archived elsewhere",
          created_at: "2026-08-20T10:00:00Z",
          repository: "posthog/example",
        },
      ],
      isComplete: true,
    });

    renderHook(() => useServerArchiveSync(), { wrapper });

    await waitFor(() =>
      expect(archiveLocally).toHaveBeenCalledWith({
        taskId: "t1",
        title: "Archived elsewhere",
        taskCreatedAt: "2026-08-20T10:00:00Z",
        repository: "posthog/example",
      }),
    );
    expect(useServerArchiveSyncStore.getState().syncedTaskIds).toContain("t1");
    expect(apiClient.getTasksWithStatus).toHaveBeenCalledWith(
      { archived: true, limit: 100 },
      { fetchAll: true },
    );
    expect(refreshArchiveState).toHaveBeenCalledOnce();
  });

  it("does not rearchive a local restore while its server update is pending", async () => {
    apiClient.setTaskArchived.mockRejectedValue(new Error("offline"));
    apiClient.getTasksWithStatus.mockResolvedValue({
      tasks: [
        {
          id: "t1",
          title: "Restored here",
          created_at: "2026-08-20T10:00:00Z",
          repository: null,
        },
      ],
      isComplete: true,
    });
    useServerArchiveSyncStore.setState({
      syncedTaskIds: [],
      pendingUnarchiveTaskIds: ["t1"],
    });

    renderHook(() => useServerArchiveSync(), { wrapper });

    await waitFor(() =>
      expect(apiClient.getTasksWithStatus).toHaveBeenCalled(),
    );
    expect(archiveLocally).not.toHaveBeenCalled();
    expect(
      useServerArchiveSyncStore.getState().pendingUnarchiveTaskIds,
    ).toContain("t1");
  });
});
