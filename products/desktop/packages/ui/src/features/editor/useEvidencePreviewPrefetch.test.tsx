import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterAll, afterEach, describe, expect, it, vi } from "vitest";
import { evidencePreviewQueryKey } from "./evidencePreview";
import {
  prefetchEvidencePreview,
  useEvidencePreviewPrefetch,
  whenViewSettles,
} from "./useEvidencePreviewPrefetch";

const eagerEnabled = vi.hoisted(() => ({ value: false }));
const prefetchSpy = vi.hoisted(() =>
  vi.fn(async (_client: unknown, _target: unknown, _source: string) => null),
);
const fakeClient = vi.hoisted(() => ({
  id: "fake-client",
})) as unknown as PostHogAPIClient;

vi.mock("../feature-flags/useEvidencePreviewEagerLoading", () => ({
  useEvidencePreviewEagerLoading: () => eagerEnabled.value,
}));
vi.mock("../auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => fakeClient,
}));
vi.mock("./evidencePreviewAnalytics", () => ({
  fetchEvidencePreviewTimed: prefetchSpy,
}));

// jsdom has neither IntersectionObserver nor requestIdleCallback; stub both
// for the file so tests can drive "the link entered the viewport" and "the
// view went idle" directly, with a cancel that really removes a queued idle
// callback. Module-scope stubs avoid racing component cleanups against
// afterEach unstubbing.
type IOCallback = (entries: Array<{ isIntersecting: boolean }>) => void;
const io = vi.hoisted(() => ({
  callback: null as IOCallback | null,
  observed: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}));

class IntersectionObserverStub {
  constructor(callback: IOCallback) {
    io.callback = callback;
  }
  observe = io.observed;
  unobserve = io.unobserve;
  disconnect = io.disconnect;
}

const idle = vi.hoisted(() => ({
  nextId: 0,
  callbacks: new Map<number, () => void>(),
}));

vi.stubGlobal("IntersectionObserver", IntersectionObserverStub);
vi.stubGlobal("requestIdleCallback", (callback: () => void) => {
  const id = ++idle.nextId;
  idle.callbacks.set(id, callback);
  return id;
});
vi.stubGlobal("cancelIdleCallback", (id: number) => {
  idle.callbacks.delete(id);
});

afterEach(() => {
  vi.clearAllMocks();
  idle.callbacks.clear();
  io.callback = null;
  eagerEnabled.value = false;
});

afterAll(() => {
  vi.unstubAllGlobals();
});

function intersect(visible: boolean) {
  const callback = io.callback;
  if (!callback) throw new Error("no observer attached");
  act(() => callback([{ isIntersecting: visible }]));
}

function runIdleCallbacks() {
  const callbacks = [...idle.callbacks.values()];
  idle.callbacks.clear();
  act(() => {
    for (const callback of callbacks) callback();
  });
}

function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { queryClient, wrapper };
}

describe("useEvidencePreviewPrefetch", () => {
  it("loads the preview in the background once the link becomes visible", async () => {
    eagerEnabled.value = true;
    const { queryClient, wrapper } = makeWrapper();
    const target = { kind: "insight", id: "9pQx3" };
    const element = document.createElement("a");

    const { unmount } = renderHook(
      () => useEvidencePreviewPrefetch(target, element),
      { wrapper },
    );

    expect(io.observed).toHaveBeenCalledWith(element);
    intersect(true);
    // Visibility alone fetches nothing: the fetch waits for the view to idle.
    expect(prefetchSpy).not.toHaveBeenCalled();
    runIdleCallbacks();

    await waitFor(() => expect(prefetchSpy).toHaveBeenCalledTimes(1));
    expect(prefetchSpy).toHaveBeenCalledWith(
      fakeClient,
      { kind: "insight", id: "9pQx3" },
      "prefetch",
    );
    expect(
      queryClient.getQueryState(evidencePreviewQueryKey(target))?.status,
    ).toBe("success");
    unmount();
  });

  it("never attaches the observer while the eager-loading flag is off", () => {
    const { wrapper } = makeWrapper();
    const element = document.createElement("a");
    eagerEnabled.value = false;

    renderHook(
      () => useEvidencePreviewPrefetch({ kind: "insight", id: "x" }, element),
      { wrapper },
    );
    runIdleCallbacks();

    expect(io.observed).not.toHaveBeenCalled();
    expect(prefetchSpy).not.toHaveBeenCalled();
  });

  it("waits for visibility before prefetching, even with the flag on", () => {
    eagerEnabled.value = true;
    const { wrapper } = makeWrapper();
    const element = document.createElement("a");

    renderHook(
      () => useEvidencePreviewPrefetch({ kind: "insight", id: "x" }, element),
      { wrapper },
    );
    // Below the fold: a non-intersecting entry must not schedule anything.
    intersect(false);
    runIdleCallbacks();

    expect(prefetchSpy).not.toHaveBeenCalled();
    expect(io.disconnect).not.toHaveBeenCalled();
  });

  it("cancels a scheduled prefetch when the link unmounts before idle", () => {
    eagerEnabled.value = true;
    const { wrapper } = makeWrapper();
    const element = document.createElement("a");

    const { unmount } = renderHook(
      () => useEvidencePreviewPrefetch({ kind: "insight", id: "x" }, element),
      { wrapper },
    );
    intersect(true);
    unmount();
    runIdleCallbacks();

    expect(io.disconnect).toHaveBeenCalled();
    expect(prefetchSpy).not.toHaveBeenCalled();
  });

  it("skips the fetch when the cache already holds a fresh preview", async () => {
    eagerEnabled.value = true;
    const { queryClient, wrapper } = makeWrapper();
    const target = { kind: "insight", id: "9pQx3" };
    queryClient.setQueryData(evidencePreviewQueryKey(target), {
      title: "Checkout funnel",
    });
    const element = document.createElement("a");

    renderHook(() => useEvidencePreviewPrefetch(target, element), { wrapper });
    intersect(true);
    runIdleCallbacks();
    await waitFor(() => expect(io.disconnect).toHaveBeenCalled());

    expect(prefetchSpy).not.toHaveBeenCalled();
    expect(queryClient.getQueryData(evidencePreviewQueryKey(target))).toEqual({
      title: "Checkout funnel",
    });
  });
});

describe("prefetchEvidencePreview", () => {
  it("marks the lookup auth-scoped so project switches purge it", async () => {
    const { queryClient } = makeWrapper();
    const target = { kind: "insight", id: "9pQx3" };

    await prefetchEvidencePreview(queryClient, fakeClient, target);

    const query = queryClient.getQueryCache().find({
      queryKey: evidencePreviewQueryKey(target) as unknown as string[],
    });
    expect(query?.meta?.authScoped).toBe(true);
    expect(prefetchSpy).toHaveBeenCalledTimes(1);
  });
});

describe("whenViewSettles", () => {
  it("falls back to a timer where requestIdleCallback is unavailable", async () => {
    delete (globalThis as Record<string, unknown>).requestIdleCallback;
    delete (globalThis as Record<string, unknown>).cancelIdleCallback;
    let ran = false;
    whenViewSettles(() => {
      ran = true;
    }, 2000);
    expect(ran).toBe(false);
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(ran).toBe(true);
    // Restore the stubs for any later runs in this file.
    vi.stubGlobal("requestIdleCallback", (callback: () => void) => {
      const id = ++idle.nextId;
      idle.callbacks.set(id, callback);
      return id;
    });
  });
});
