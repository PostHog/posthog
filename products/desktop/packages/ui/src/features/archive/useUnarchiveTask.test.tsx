import type {
  ContextMenuOutcome,
  DeleteOutcome,
  RestoreOutcome,
} from "@posthog/core/archive/archivedTasksController";
import { WORKSPACE_QUERY_KEY } from "@posthog/ui/features/workspace/identifiers";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const ARCHIVE_FILTER = { queryKey: [["archive"]] };

const controller = vi.hoisted(() => ({
  restore: vi.fn(),
  remove: vi.fn(),
  runContextMenuAction: vi.fn(),
}));

vi.mock("@posthog/di/react", () => ({
  useService: () => controller,
}));

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    archive: {
      pathFilter: () => ARCHIVE_FILTER,
    },
  }),
}));

import { useUnarchiveTask } from "./useUnarchiveTask";

let queryClient: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useUnarchiveTask", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  it("invalidates the workspace, archive and tasks caches together when an archived task is deleted", async () => {
    // Regression: delete once skipped WORKSPACE_QUERY_KEY, leaving stale sidebar rows.
    controller.remove.mockResolvedValue({ kind: "deleted" } as DeleteOutcome);
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    const refetchSpy = vi.spyOn(queryClient, "refetchQueries");
    const { result } = renderHook(() => useUnarchiveTask(), { wrapper });

    await act(async () => {
      await result.current.remove("t1");
    });

    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: WORKSPACE_QUERY_KEY,
    });
    expect(invalidateSpy).toHaveBeenCalledWith(ARCHIVE_FILTER);
    expect(refetchSpy).toHaveBeenCalledWith({ queryKey: ["tasks"] });
  });

  it.each<[string, DeleteOutcome, boolean]>([
    ["deleted", { kind: "deleted" }, true],
    ["error", { kind: "error", message: "nope" }, false],
  ])(
    "remove() with outcome %s invalidates the workspace query: %s",
    async (_name, outcome, shouldInvalidate) => {
      controller.remove.mockResolvedValue(outcome);
      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
      const { result } = renderHook(() => useUnarchiveTask(), { wrapper });

      await act(async () => {
        await result.current.remove("t1");
      });

      if (shouldInvalidate) {
        expect(invalidateSpy).toHaveBeenCalledWith({
          queryKey: WORKSPACE_QUERY_KEY,
        });
      } else {
        expect(invalidateSpy).not.toHaveBeenCalled();
      }
    },
  );

  it.each<[string, RestoreOutcome, boolean]>([
    ["restored", { kind: "restored", navigateToTaskId: "t1" }, true],
    [
      "branch-not-found",
      { kind: "branch-not-found", taskId: "t1", branchName: "b" },
      false,
    ],
    ["error", { kind: "error", message: "nope" }, false],
  ])(
    "restore() with outcome %s invalidates the workspace query: %s",
    async (_name, outcome, shouldInvalidate) => {
      controller.restore.mockResolvedValue(outcome);
      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
      const { result } = renderHook(() => useUnarchiveTask(), { wrapper });

      await act(async () => {
        await result.current.restore("t1", true);
      });

      if (shouldInvalidate) {
        expect(invalidateSpy).toHaveBeenCalledWith({
          queryKey: WORKSPACE_QUERY_KEY,
        });
      } else {
        expect(invalidateSpy).not.toHaveBeenCalled();
      }
    },
  );

  it.each<[string, ContextMenuOutcome, boolean]>([
    ["noop", { kind: "noop" }, false],
    ["menu-error", { kind: "menu-error", message: "nope" }, false],
    [
      "restore -> restored",
      {
        kind: "restore",
        outcome: { kind: "restored", navigateToTaskId: "t1" },
      },
      true,
    ],
    [
      "restore -> branch-not-found",
      {
        kind: "restore",
        outcome: {
          kind: "branch-not-found",
          taskId: "t1",
          branchName: "b",
        },
      },
      false,
    ],
    [
      "delete -> deleted",
      { kind: "delete", outcome: { kind: "deleted" } },
      true,
    ],
    [
      "delete -> error",
      { kind: "delete", outcome: { kind: "error", message: "nope" } },
      false,
    ],
  ])(
    "runContextMenuAction() with outcome %s invalidates the workspace query: %s",
    async (_name, outcome, shouldInvalidate) => {
      controller.runContextMenuAction.mockResolvedValue(outcome);
      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
      const { result } = renderHook(() => useUnarchiveTask(), { wrapper });

      await act(async () => {
        await result.current.runContextMenuAction("t1", "Task 1", true);
      });

      if (shouldInvalidate) {
        expect(invalidateSpy).toHaveBeenCalledWith({
          queryKey: WORKSPACE_QUERY_KEY,
        });
      } else {
        expect(invalidateSpy).not.toHaveBeenCalled();
      }
    },
  );
});
