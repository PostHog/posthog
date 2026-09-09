import { dashboardRecordSchema } from "@posthog/core/canvas/dashboardSchemas";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { expect, it, vi } from "vitest";
import { useAllCanvases, useDashboards } from "./useDashboards";

const records = vi.hoisted(() => ({
  canvases: [] as unknown[],
  boards: [] as unknown[],
}));
vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    dashboards: {
      list: {
        queryOptions: (_input: unknown, options: object) => ({
          ...options,
          queryKey: ["canvases"],
          queryFn: async () => records.canvases,
        }),
      },
      listAll: {
        queryOptions: (_input: unknown, options: object) => ({
          ...options,
          queryKey: ["all-canvases"],
          queryFn: async () => records.canvases,
        }),
      },
    },
  }),
}));
vi.mock("@posthog/ui/features/sketchpad/hooks/useSketchpadsAsCanvases", () => ({
  useSpaceSketchpadsAsCanvases: () => records.boards,
  useAllSketchpadsAsCanvases: () => records.boards,
}));

it.each(["space", "all"] as const)(
  "merges %s canvases and sketchpads in one recency order",
  async (scope) => {
    const record = (
      id: string,
      updatedAt: number,
      canvasType: "canvas" | "sketchpad",
    ) =>
      dashboardRecordSchema.parse({
        id,
        channelId: "space",
        name: id,
        canvasType,
        updatedAt,
        createdAt: 0,
      });
    records.canvases = [
      record("older", 1, "canvas"),
      record("newest", 3, "canvas"),
    ];
    records.boards = [record("board", 2, "sketchpad")];
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result, unmount } = renderHook(
      scope === "space" ? () => useDashboards("space") : useAllCanvases,
      { wrapper },
    );
    await waitFor(() =>
      expect(result.current.dashboards.map((record) => record.id)).toEqual([
        "newest",
        "board",
        "older",
      ]),
    );
    unmount();
    queryClient.clear();
  },
);
