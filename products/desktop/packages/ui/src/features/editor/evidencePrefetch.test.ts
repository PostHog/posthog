import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { evidencePreviewQueryKey } from "./evidencePreview";

const fetchEvidencePreview = vi.hoisted(() => vi.fn());
vi.mock("./evidencePreview", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./evidencePreview")>()),
  fetchEvidencePreview,
}));

const client = {} as PostHogAPIClient;

/** The queue is module state, so each case gets its own copy of the module. */
async function loadQueue() {
  vi.resetModules();
  return await import("./evidencePrefetch");
}

/** Let the idle scheduler's macrotask run, then any resolved fetches settle. */
async function settle() {
  await vi.advanceTimersByTimeAsync(0);
}

describe("evidencePrefetch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    fetchEvidencePreview.mockReset();
  });

  it("warms the entry the hover card reads", async () => {
    const { enqueueEvidencePrefetch } = await loadQueue();
    const queryClient = new QueryClient();
    fetchEvidencePreview.mockResolvedValue({
      title: "signals-report-canvases",
    });

    enqueueEvidencePrefetch(queryClient, client, {
      kind: "flag",
      id: "831957",
    });
    await settle();

    expect(
      queryClient.getQueryData(
        evidencePreviewQueryKey({ kind: "flag", id: "831957" }),
      ),
    ).toEqual({ title: "signals-report-canvases" });
  });

  it("runs at most three lookups at once", async () => {
    const { enqueueEvidencePrefetch } = await loadQueue();
    const queryClient = new QueryClient();
    const release: Array<() => void> = [];
    fetchEvidencePreview.mockImplementation(
      () => new Promise<null>((resolve) => release.push(() => resolve(null))),
    );

    for (const id of ["1", "2", "3", "4", "5"]) {
      enqueueEvidencePrefetch(queryClient, client, { kind: "insight", id });
    }
    await settle();
    expect(fetchEvidencePreview).toHaveBeenCalledTimes(3);

    release[0]();
    await settle();
    expect(fetchEvidencePreview).toHaveBeenCalledTimes(4);
  });

  it("resolves a repeated reference once", async () => {
    const { enqueueEvidencePrefetch } = await loadQueue();
    const queryClient = new QueryClient();
    fetchEvidencePreview.mockResolvedValue(null);

    enqueueEvidencePrefetch(queryClient, client, { kind: "flag", id: "42" });
    enqueueEvidencePrefetch(queryClient, client, { kind: "flag", id: "42" });
    await settle();

    expect(fetchEvidencePreview).toHaveBeenCalledTimes(1);
  });

  it("drops a job cancelled before it starts", async () => {
    const { enqueueEvidencePrefetch } = await loadQueue();
    const queryClient = new QueryClient();
    fetchEvidencePreview.mockResolvedValue(null);

    const cancel = enqueueEvidencePrefetch(queryClient, client, {
      kind: "flag",
      id: "42",
    });
    cancel();
    await settle();

    expect(fetchEvidencePreview).not.toHaveBeenCalled();
  });

  it("leaves no cached failure for the hover card to inherit", async () => {
    const { enqueueEvidencePrefetch } = await loadQueue();
    const queryClient = new QueryClient();
    fetchEvidencePreview.mockRejectedValue(new Error("timeout"));

    enqueueEvidencePrefetch(queryClient, client, { kind: "flag", id: "42" });
    await settle();

    // The card mounts with retryOnMount off, so a lingering error entry would
    // pin it to the static fallback instead of letting it retry.
    expect(
      queryClient.getQueryState(
        evidencePreviewQueryKey({ kind: "flag", id: "42" }),
      ),
    ).toBeUndefined();
  });
});
