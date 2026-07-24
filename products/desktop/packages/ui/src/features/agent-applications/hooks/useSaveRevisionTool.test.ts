import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Capture the mutationFn + onSuccess handed to react-query so we can drive the
// PUT call and the "invalidate only when the compile actually persisted" branch
// without a live QueryClient.
let mutationFn: (vars: { toolId: string; body: unknown }) => Promise<unknown>;
let onSuccess: ((result: unknown) => void) | undefined;
let invalidateQueries: ReturnType<typeof vi.fn>;

vi.mock("@tanstack/react-query", () => ({
  useMutation: (opts: {
    mutationFn: typeof mutationFn;
    onSuccess?: (result: unknown) => void;
  }) => {
    mutationFn = opts.mutationFn;
    onSuccess = opts.onSuccess;
    return { mutate: vi.fn() };
  },
  useQueryClient: () => {
    invalidateQueries = vi.fn();
    return { invalidateQueries };
  },
}));

const client = {
  putRevisionTool: vi.fn(),
};

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useAuthenticatedClient: () => client,
}));
vi.mock("../../auth/store", () => ({
  useAuthStateValue: () => 7,
}));

import { agentApplicationsKeys } from "./agentApplicationsKeys";
import { useSaveRevisionTool } from "./useSaveRevisionTool";

describe("useSaveRevisionTool", () => {
  beforeEach(() => {
    client.putRevisionTool.mockReset();
  });

  it("PUTs the tool body via the client", async () => {
    client.putRevisionTool.mockResolvedValue({ ok: true });
    renderHook(() => useSaveRevisionTool("agent", "rev-1"));
    const body = { description: "d", args_schema: {}, source: "x" };

    await mutationFn({ toolId: "t1", body });

    expect(client.putRevisionTool).toHaveBeenCalledWith(
      "agent",
      "rev-1",
      "t1",
      body,
    );
  });

  it("invalidates the bundle query when the compile persisted (ok)", () => {
    renderHook(() => useSaveRevisionTool("agent", "rev-1"));
    onSuccess?.({ ok: true, tool_id: "t1", capabilities: {} });

    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: agentApplicationsKeys.bundle(7, "agent", "rev-1"),
    });
  });

  it("does NOT invalidate when the compile failed (422, nothing persisted)", () => {
    renderHook(() => useSaveRevisionTool("agent", "rev-1"));
    onSuccess?.({
      ok: false,
      error: "tool_compile_failed",
      tool_id: "t1",
      errors: [],
    });

    expect(invalidateQueries).not.toHaveBeenCalled();
  });
});
