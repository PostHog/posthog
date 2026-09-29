import { runLoop } from "@posthog/api-client/loops";
import { useLoopsHogFlowsEnabled } from "@posthog/ui/features/feature-flags/useLoopsHogFlowsEnabled";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { runLoopHogFlow } from "../loopHogFlowWrites";
import { loopsKeys } from "./loopsKeys";
import { useRunLoop } from "./useLoopMutations";

vi.mock("@posthog/api-client/loops", () => ({
  runLoop: vi.fn(),
}));
vi.mock("@posthog/api-client/hogFlowLoops", () => ({
  deleteHogFlow: vi.fn(),
}));
vi.mock("@posthog/ui/features/feature-flags/useLoopsHogFlowsEnabled", () => ({
  useLoopsHogFlowsEnabled: vi.fn(),
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

const FIRED = {
  created: true,
  reason: "created",
  task_id: null,
  task_run_id: null,
} as const;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(runLoop).mockResolvedValue(FIRED);
  vi.mocked(runLoopHogFlow).mockResolvedValue(FIRED);
});

describe("useRunLoop", () => {
  it.each([
    { hogFlows: true, listKey: loopsKeys.hogFlowList("1") },
    { hogFlows: false, listKey: loopsKeys.list("1") },
  ])(
    "marks the cached loop list stale after a run (hogFlows: $hogFlows)",
    async ({ hogFlows, listKey }) => {
      vi.mocked(useLoopsHogFlowsEnabled).mockReturnValue(hogFlows);
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
    },
  );
});
