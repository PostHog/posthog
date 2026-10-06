import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiClient = vi.hoisted(() => ({
  getTasksPage: vi.fn(),
  setTaskArchived: vi.fn(),
}));
const archiveLocally = vi.hoisted(() => vi.fn());
const refreshArchiveState = vi.hoisted(() => vi.fn());
const serverArchiveScope = '["us","user-a",42]';

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => apiClient,
}));

vi.mock("./useServerArchiveScope", () => ({
  useServerArchiveScope: () => serverArchiveScope,
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
    apiClient.getTasksPage.mockResolvedValue({
      tasks: [],
      count: 0,
    });
    archiveLocally.mockResolvedValue(undefined);
    refreshArchiveState.mockResolvedValue(undefined);
    archivedIds.current = new Set();
    useServerArchiveSyncStore.setState({
      syncedTaskIds: [],
      pendingUnarchiveTaskIds: [],
      archiveImportOffsets: {},
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
    apiClient.getTasksPage.mockResolvedValue({
      tasks: [
        {
          id: "t1",
          title: "Archived elsewhere",
          created_at: "2026-08-20T10:00:00Z",
          repository: "posthog/example",
        },
      ],
      count: 1,
    });

    renderHook(() => useServerArchiveSync(), { wrapper });

    await waitFor(() =>
      expect(archiveLocally).toHaveBeenCalledWith({
        taskId: "t1",
        title: "Archived elsewhere",
        taskCreatedAt: "2026-08-20T10:00:00Z",
        repository: "posthog/example",
        serverArchiveScope,
      }),
    );
    expect(useServerArchiveSyncStore.getState().syncedTaskIds).toContain("t1");
    expect(apiClient.getTasksPage).toHaveBeenCalledWith({
      archived: true,
      limit: 100,
      offset: 0,
    });
    expect(refreshArchiveState).toHaveBeenCalledOnce();
  });

  it("continues a large server archive from its durable offset", async () => {
    useServerArchiveSyncStore.setState({
      archiveImportOffsets: { [serverArchiveScope]: 100 },
    });
    apiClient.getTasksPage.mockResolvedValue({
      tasks: [
        {
          id: "t101",
          title: "Older archived task",
          created_at: "2026-08-01T10:00:00Z",
          repository: null,
        },
      ],
      count: 500,
    });

    const { rerender } = renderHook(() => useServerArchiveSync(), { wrapper });

    await waitFor(() => expect(archiveLocally).toHaveBeenCalledOnce());
    archivedIds.current = new Set(["t101"]);
    await act(async () => rerender());
    expect(apiClient.getTasksPage).toHaveBeenCalledOnce();
    expect(apiClient.getTasksPage).toHaveBeenCalledWith({
      archived: true,
      limit: 100,
      offset: 100,
    });
    expect(
      useServerArchiveSyncStore.getState().archiveImportOffsets[
        serverArchiveScope
      ],
    ).toBe(101);
  });

  it("does not rearchive a local restore while its server update is pending", async () => {
    apiClient.setTaskArchived.mockRejectedValue(new Error("offline"));
    apiClient.getTasksPage.mockResolvedValue({
      tasks: [
        {
          id: "t1",
          title: "Restored here",
          created_at: "2026-08-20T10:00:00Z",
          repository: null,
        },
      ],
      count: 1,
    });
    useServerArchiveSyncStore.setState({
      syncedTaskIds: [],
      pendingUnarchiveTaskIds: ["t1"],
    });

    renderHook(() => useServerArchiveSync(), { wrapper });

    await waitFor(() => expect(apiClient.getTasksPage).toHaveBeenCalled());
    expect(archiveLocally).not.toHaveBeenCalled();
    expect(
      useServerArchiveSyncStore.getState().pendingUnarchiveTaskIds,
    ).toContain("t1");
  });
});
