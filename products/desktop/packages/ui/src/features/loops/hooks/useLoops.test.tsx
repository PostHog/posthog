import { listLoopHogFlows } from "@posthog/api-client/hogFlowLoops";
import type { LoopSchemas } from "@posthog/api-client/loops";
import { useLoopsHogFlowsEnabled } from "@posthog/ui/features/feature-flags/useLoopsHogFlowsEnabled";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { loopsKeys } from "./loopsKeys";
import { useLoopLimits, useLoops } from "./useLoops";

vi.mock("@posthog/api-client/hogFlowLoops", () => ({
  listLoopHogFlows: vi.fn(),
}));
vi.mock("@posthog/api-client/loops", () => ({
  listLoops: vi.fn(),
}));
vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  AUTH_SCOPED_QUERY_META: {},
}));
vi.mock("@posthog/ui/features/feature-flags/useLoopsHogFlowsEnabled", () => ({
  useLoopsHogFlowsEnabled: vi.fn(),
}));
vi.mock("./useLoopsClient", () => ({
  useLoopsClient: () => ({ client: {}, projectId: "1" }),
}));
vi.mock("../loopHogFlowMapping", () => ({
  hogFlowToLoop: (flow: { id: string }) => ({ id: flow.id }),
}));

const mockedListLoopHogFlows = vi.mocked(listLoopHogFlows);
const mockedHogFlowsEnabled = vi.mocked(useLoopsHogFlowsEnabled);

function wrapperFor(queryClient: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useLoops", () => {
  it("drops archived workflows from the workflow-backed list", async () => {
    mockedHogFlowsEnabled.mockReturnValue(true);
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

describe("useLoopLimits", () => {
  const cachedPage = {
    results: [],
    max_loops_per_team: 5,
    total_loop_count: 5,
  } as unknown as LoopSchemas.PaginatedLoopList;

  // The loops query is disabled for workflow-backed loops, but a page cached
  // before the flag flipped would still be served.
  it.each([
    { hogFlows: true, expected: null },
    { hogFlows: false, expected: { max: 5, used: 5, atLimit: true } },
  ])(
    "returns $expected from a cached page when hogFlows is $hogFlows",
    ({ hogFlows, expected }) => {
      mockedHogFlowsEnabled.mockReturnValue(hogFlows);
      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      });
      queryClient.setQueryData(loopsKeys.list("1"), cachedPage);

      const { result } = renderHook(() => useLoopLimits(), {
        wrapper: wrapperFor(queryClient),
      });

      expect(result.current).toEqual(expected);
    },
  );
});
