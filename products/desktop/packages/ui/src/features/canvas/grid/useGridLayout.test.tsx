import type {
  CanvasLayoutResult,
  LayoutOperation,
} from "@posthog/core/canvas/gridLayoutSchemas";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const LAYOUT_KEY = ["dashboards", "layout", "canvas-1"];

const mocks = vi.hoisted(() => ({
  patchLayout: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    dashboards: {
      layout: { queryKey: () => LAYOUT_KEY },
      patchLayout: {
        mutationOptions: (options: Record<string, unknown>) => ({
          mutationFn: (input: unknown) => mocks.patchLayout(input),
          ...options,
        }),
      },
    },
  }),
}));

vi.mock("@posthog/ui/features/notifications/errorDetails", () => ({
  toastError: mocks.toastError,
}));

import { usePatchLayout } from "./useGridLayout";

const MOVE: LayoutOperation[] = [
  { op: "update_placement", id: "p1", changes: { x: 1 } },
];

function layoutAt(versionId: string): CanvasLayoutResult {
  return {
    layout: {
      schemaVersion: 1,
      grid: { columns: 6, rowHeight: 96, gap: 8 },
      placements: [],
    },
    currentVersionId: versionId,
  };
}

let queryClient: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("usePatchLayout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    queryClient.setQueryData(LAYOUT_KEY, layoutAt("v1"));
  });

  // Two gestures can finish before the first patch answers. Sending both
  // against the same head means the server rejects the second as a conflict and
  // the drag or resize silently disappears on the rebase refetch.
  it("bases a queued patch on the version the previous patch created", async () => {
    const expected: unknown[] = [];
    let releaseFirst = (): void => {};
    const firstInFlight = new Promise<void>((resolve) => {
      releaseFirst = resolve;
    });
    mocks.patchLayout
      .mockImplementationOnce(async (input: Record<string, unknown>) => {
        expected.push(input.expectedCurrentVersionId);
        await firstInFlight;
        return layoutAt("v2");
      })
      .mockImplementationOnce(async (input: Record<string, unknown>) => {
        expected.push(input.expectedCurrentVersionId);
        return layoutAt("v3");
      });

    const { result } = renderHook(() => usePatchLayout("canvas-1"), {
      wrapper,
    });
    await act(async () => {
      const first = result.current.patch(MOVE);
      const second = result.current.patch(MOVE);
      releaseFirst();
      await Promise.all([first, second]);
    });

    expect(expected).toEqual(["v1", "v2"]);
    expect(queryClient.getQueryData(LAYOUT_KEY)).toEqual(layoutAt("v3"));
  });

  // A rejected patch must not wedge the queue: the next gesture still runs.
  it("reports a rejected patch as null and keeps accepting later ones", async () => {
    mocks.patchLayout
      .mockRejectedValueOnce(new Error("version_conflict"))
      .mockResolvedValueOnce(layoutAt("v2"));

    const { result } = renderHook(() => usePatchLayout("canvas-1"), {
      wrapper,
    });
    let rejected: CanvasLayoutResult | null = layoutAt("unset");
    let accepted: CanvasLayoutResult | null = null;
    await act(async () => {
      rejected = await result.current.patch(MOVE);
      accepted = await result.current.patch(MOVE);
    });

    expect(rejected).toBeNull();
    expect(accepted).toEqual(layoutAt("v2"));
    expect(mocks.toastError).toHaveBeenCalledTimes(1);
  });
});
