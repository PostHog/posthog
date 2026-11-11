import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { runLoopHogFlow } from "../loopHogFlowWrites";
import { loopsKeys } from "./loopsKeys";
import { useRunLoop } from "./useLoopMutations";

vi.mock("@posthog/api-client/hogFlowLoops", () => ({
  deleteHogFlow: vi.fn(),
}));
vi.mock("../loopHogFlowWrites", () => ({
  LoopScheduleSaveError: class extends Error {},
  createLoopHogFlow: vi.fn(),
  runLoopHogFlow: vi.fn(),
  setLoopHogFlowEnabled: vi.fn(),
  updateLoopHogFlow: vi.fn(),
}));
vi.mock("../loopHogFlowMapping", () => ({
  formValuesToHogFlowWrite: vi.fn(),
  hogFlowToLoop: vi.fn(),
}));
vi.mock("./useLoopsClient", () => ({
  useLoopsClient: () => ({ client: {}, projectId: "1" }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(runLoopHogFlow).mockResolvedValue();
});

describe("useRunLoop", () => {
  it("marks the cached loop list stale after a run", async () => {
    const listKey = loopsKeys.list("1");
    const queryClient = new QueryClient();
    queryClient.setQueryData(listKey, []);
    const { result } = renderHook(() => useRunLoop("loop-1"), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={queryClient}>
          {children}
        </QueryClientProvider>
      ),
    });

    await result.current.mutateAsync();

    expect(queryClient.getQueryState(listKey)?.isInvalidated).toBe(true);
  });
});
