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

const prefetchSpy = vi.hoisted(() =>
  vi.fn(async (_client: unknown, _target: unknown, _source: string) => null),
);
const fakeClient = vi.hoisted(() => ({
  id: "fake-client",
})) as unknown as PostHogAPIClient;

vi.mock("../auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => fakeClient,
}));
vi.mock("./evidencePreviewAnalytics", () => ({
  fetchEvidencePreviewTimed: prefetchSpy,
}));

// jsdom has neither API. Module scope, not beforeEach: afterEach unstubbing
// runs before unmount cleanups, which call the stubs.
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
    const { queryClient, wrapper } = makeWrapper();
    const target = { kind: "insight", id: "9pQx3" };
    const element = document.createElement("a");

    const { unmount } = renderHook(
      () => useEvidencePreviewPrefetch(target, element),
      { wrapper },
    );

    expect(io.observed).toHaveBeenCalledWith(element);
    intersect(true);
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

  it("waits for visibility before prefetching", () => {
    const { wrapper } = makeWrapper();
    const element = document.createElement("a");

    renderHook(
      () => useEvidencePreviewPrefetch({ kind: "insight", id: "x" }, element),
      { wrapper },
    );
    intersect(false);
    runIdleCallbacks();

    expect(prefetchSpy).not.toHaveBeenCalled();
    expect(io.disconnect).not.toHaveBeenCalled();
  });

  it("cancels a scheduled prefetch when the link unmounts before idle", () => {
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
    vi.stubGlobal("requestIdleCallback", (callback: () => void) => {
      const id = ++idle.nextId;
      idle.callbacks.set(id, callback);
      return id;
    });
  });
});
