import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fakeClient = {} as PostHogAPIClient;
vi.mock("../../auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => fakeClient,
}));

const fetchEvidencePreview = vi.hoisted(() => vi.fn());
vi.mock("../evidencePreview", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../evidencePreview")>()),
  fetchEvidencePreview,
}));

import { ANONYMOUS_AUTH_STATE, useAuthStore } from "../../auth/store";
import { EvidenceRefChip } from "./EvidenceRefChip";

/** Reports every observed element as visible, the way a chip on screen is. */
function observeAsVisible() {
  class VisibleIntersectionObserver {
    constructor(private readonly callback: IntersectionObserverCallback) {}
    observe(element: Element) {
      this.callback(
        [
          {
            isIntersecting: true,
            target: element,
          } as IntersectionObserverEntry,
        ],
        this as unknown as IntersectionObserver,
      );
    }
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
  }
  vi.stubGlobal("IntersectionObserver", VisibleIntersectionObserver);
}

describe("EvidenceRefChip preview warm-up", () => {
  beforeEach(() => {
    fetchEvidencePreview.mockReset();
    fetchEvidencePreview.mockResolvedValue({ title: "new-checkout-flow" });
    observeAsVisible();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    useAuthStore.setState({ authState: ANONYMOUS_AUTH_STATE });
  });

  // A chip renders as an anchor when the object has a page to open and a span
  // when it does not; the warm-up hangs off whichever element is rendered.
  it.each([
    ["links out", { cloudRegion: "us" as const, currentProjectId: 2 }],
    ["has no page to open", { cloudRegion: null, currentProjectId: null }],
  ])("warms the preview for a visible chip that %s", async (_case, auth) => {
    useAuthStore.setState({
      authState: { ...ANONYMOUS_AUTH_STATE, ...auth },
    });

    render(
      <QueryClientProvider client={new QueryClient()}>
        <EvidenceRefChip target={{ kind: "flag", id: "42" }}>
          new-checkout-flow
        </EvidenceRefChip>
      </QueryClientProvider>,
    );

    await waitFor(() =>
      expect(fetchEvidencePreview).toHaveBeenCalledWith(fakeClient, {
        kind: "flag",
        id: "42",
      }),
    );
  });

  it("leaves an offscreen chip alone", async () => {
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
        takeRecords() {
          return [];
        }
      },
    );
    vi.useFakeTimers();

    try {
      render(
        <QueryClientProvider client={new QueryClient()}>
          <EvidenceRefChip target={{ kind: "flag", id: "42" }}>
            new-checkout-flow
          </EvidenceRefChip>
        </QueryClientProvider>,
      );
      // The queue drains from a scheduled callback, so run the clock past it
      // rather than assert on an empty mock the warm-up never had time to fill.
      await vi.advanceTimersByTimeAsync(1000);

      expect(fetchEvidencePreview).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });
});
