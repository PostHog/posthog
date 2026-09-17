import { listLoopHogFlows } from "@posthog/api-client/hogFlowLoops";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { useLoops } from "./useLoops";

vi.mock("@posthog/api-client/hogFlowLoops", () => ({
  listLoopHogFlows: vi.fn(),
}));
vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  AUTH_SCOPED_QUERY_META: {},
}));
vi.mock("./useLoopsClient", () => ({
  useLoopsClient: () => ({ client: {}, projectId: "1" }),
}));
vi.mock("../loopHogFlowMapping", () => ({
  hogFlowToLoop: (flow: { id: string }) => ({ id: flow.id }),
}));

const mockedListLoopHogFlows = vi.mocked(listLoopHogFlows);

function wrapperFor(queryClient: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useLoops", () => {
  it("drops archived workflows from the list", async () => {
    mockedListLoopHogFlows.mockResolvedValue({
      results: [
        { id: "live", status: "active" },
        { id: "gone", status: "archived" },
        { id: "unpublished", status: "draft" },
      ],
    } as Awaited<ReturnType<typeof listLoopHogFlows>>);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    const { result } = renderHook(() => useLoops(), {
      wrapper: wrapperFor(queryClient),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.map((loop) => loop.id)).toEqual([
      "live",
      "unpublished",
    ]);
  });
});
