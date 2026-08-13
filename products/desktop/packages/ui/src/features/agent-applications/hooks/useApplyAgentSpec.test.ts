import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Capture the mutationFn and onSuccess the hook hands to react-query so we can
// exercise the create-draft-vs-patch branching and the cache invalidation
// directly, without a live QueryClient.
let mutationFn: (vars: {
  revision: { id: string; state: string };
  spec: unknown;
}) => Promise<unknown>;
let onSuccess: (() => void) | undefined;
let invalidateQueries: ReturnType<typeof vi.fn>;

vi.mock("@tanstack/react-query", () => ({
  useMutation: (opts: {
    mutationFn: typeof mutationFn;
    onSuccess?: () => void;
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
  createAgentDraftRevisionFrom: vi.fn(),
  updateAgentRevisionSpec: vi.fn(),
  transitionAgentRevision: vi.fn(),
};

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useAuthenticatedClient: () => client,
}));
vi.mock("../../auth/store", () => ({
  useAuthStateValue: () => 1,
}));

import { agentApplicationsKeys } from "./agentApplicationsKeys";
import { useApplyAgentSpec } from "./useApplyAgentSpec";

describe("useApplyAgentSpec", () => {
  beforeEach(() => {
    client.createAgentDraftRevisionFrom.mockReset();
    client.updateAgentRevisionSpec.mockReset();
    client.transitionAgentRevision.mockReset();
  });

  it("PATCHes a draft in place — no new draft branched", async () => {
    client.updateAgentRevisionSpec.mockResolvedValue({
      id: "d1",
      state: "draft",
    });
    renderHook(() => useApplyAgentSpec("agent-slug", "app-1"));
    const spec = { models: { mode: "auto", level: "high" } };

    await mutationFn({ revision: { id: "d1", state: "draft" }, spec });

    expect(client.createAgentDraftRevisionFrom).not.toHaveBeenCalled();
    expect(client.updateAgentRevisionSpec).toHaveBeenCalledWith(
      "agent-slug",
      "d1",
      spec,
    );
  });

  it("clones to a fresh draft then PATCHes it when the source isn't a draft", async () => {
    client.createAgentDraftRevisionFrom.mockResolvedValue({
      id: "new-draft",
      state: "draft",
    });
    client.updateAgentRevisionSpec.mockResolvedValue({
      id: "new-draft",
      state: "draft",
    });
    renderHook(() => useApplyAgentSpec("agent-slug", "app-1"));
    const spec = { models: { mode: "manual", models: [{ model: "x" }] } };

    await mutationFn({ revision: { id: "live-1", state: "live" }, spec });

    expect(client.createAgentDraftRevisionFrom).toHaveBeenCalledWith(
      "app-1",
      "live-1",
    );
    expect(client.updateAgentRevisionSpec).toHaveBeenCalledWith(
      "agent-slug",
      "new-draft",
      spec,
    );
  });

  it("throws when a clone is needed but the application id is missing", async () => {
    renderHook(() => useApplyAgentSpec("agent-slug", undefined));

    await expect(
      mutationFn({ revision: { id: "live-1", state: "live" }, spec: {} }),
    ).rejects.toThrow(/Application/);
    expect(client.createAgentDraftRevisionFrom).not.toHaveBeenCalled();
  });

  it("archives the orphaned draft (and rethrows) when the PATCH fails after a clone", async () => {
    client.createAgentDraftRevisionFrom.mockResolvedValue({
      id: "new-draft",
      state: "draft",
    });
    const patchErr = new Error("spec.models: invalid");
    client.updateAgentRevisionSpec.mockRejectedValue(patchErr);
    client.transitionAgentRevision.mockResolvedValue({ id: "new-draft" });
    renderHook(() => useApplyAgentSpec("agent-slug", "app-1"));

    await expect(
      mutationFn({ revision: { id: "live-1", state: "live" }, spec: {} }),
    ).rejects.toThrow(patchErr);
    // The just-cloned, never-landed draft gets archived as cleanup.
    expect(client.transitionAgentRevision).toHaveBeenCalledWith(
      "agent-slug",
      "new-draft",
      "archive",
    );
  });

  it("does NOT archive when an in-place draft PATCH fails (nothing was cloned)", async () => {
    client.updateAgentRevisionSpec.mockRejectedValue(new Error("boom"));
    renderHook(() => useApplyAgentSpec("agent-slug", "app-1"));

    await expect(
      mutationFn({ revision: { id: "d1", state: "draft" }, spec: {} }),
    ).rejects.toThrow(/boom/);
    expect(client.createAgentDraftRevisionFrom).not.toHaveBeenCalled();
    expect(client.transitionAgentRevision).not.toHaveBeenCalled();
  });

  it("onSuccess invalidates the detail, revisions, and per-revision caches via the shared key factory", () => {
    // projectId is mocked to 1 (useAuthStateValue). Asserting against the
    // factory rather than literal arrays means these keys can't silently drift
    // from the fetch hooks that own the caches — the gap when useMutation is
    // mocked away.
    renderHook(() => useApplyAgentSpec("agent-slug", "app-1"));
    expect(onSuccess).toBeDefined();
    onSuccess?.();

    const invalidated = invalidateQueries.mock.calls.map((c) => c[0].queryKey);
    expect(invalidated).toContainEqual(
      agentApplicationsKeys.detail(1, "agent-slug"),
    );
    expect(invalidated).toContainEqual(
      agentApplicationsKeys.revisions(1, "agent-slug"),
    );
    expect(invalidated).toContainEqual(
      agentApplicationsKeys.revisionPrefix(1, "agent-slug"),
    );
  });
});
