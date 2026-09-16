import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type PropsWithChildren } from "react";
import { act, create } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { mockAreDesktopBetaTermsAccepted, mockUseAuthStore } = vi.hoisted(
  () => ({
    mockAreDesktopBetaTermsAccepted: vi.fn(),
    mockUseAuthStore: vi.fn(),
  }),
);

vi.mock("@/features/auth/stores/authStore", () => ({
  useAuthStore: mockUseAuthStore,
}));

// Not used by this hook, but loading the real one drags in the expo OAuth
// module, which vitest's node environment cannot evaluate.
vi.mock("@/features/auth/hooks/useUserQuery", () => ({
  useUserQuery: vi.fn(),
}));

vi.mock("@/lib/posthogApiClient", () => ({
  getPostHogApiClient: () => ({
    areDesktopBetaTermsAccepted: mockAreDesktopBetaTermsAccepted,
  }),
}));

import { useDesktopBetaTerms } from "./useOrgConsent";

async function waitForAssertion(assertion: () => void): Promise<void> {
  const timeoutAt = Date.now() + 2_000;
  while (Date.now() < timeoutAt) {
    try {
      assertion();
      return;
    } catch (error) {
      await new Promise((resolve) => setTimeout(resolve, 10));
      if (Date.now() >= timeoutAt) throw error;
    }
  }
}

describe("useDesktopBetaTerms", () => {
  let projectId: number | null;
  let currentResult: ReturnType<typeof useDesktopBetaTerms>;

  beforeEach(() => {
    projectId = 1;
    mockAreDesktopBetaTermsAccepted.mockReset();
    mockAreDesktopBetaTermsAccepted.mockImplementation(
      async (requested: number) => requested === 1,
    );
    mockUseAuthStore.mockImplementation((selector) =>
      selector({ isAuthenticated: true, projectId }),
    );
  });

  async function mountProbe(): Promise<{ rerender: () => Promise<void> }> {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    function HookProbe() {
      // The organization id stays put on purpose: /api/users/@me/ does not
      // move when the token's scoped teams do.
      currentResult = useDesktopBetaTerms("org-1");
      return null;
    }

    function Wrapper({ children }: PropsWithChildren) {
      return createElement(
        QueryClientProvider,
        { client: queryClient },
        children,
      );
    }

    // A fresh element every time: React bails out of re-rendering one it has
    // already seen, so reusing it would never pick a new project up.
    const tree = () => createElement(Wrapper, null, createElement(HookProbe));
    let renderer!: ReturnType<typeof create>;
    await act(async () => {
      renderer = create(tree());
      await Promise.resolve();
    });

    return {
      rerender: async () => {
        await act(async () => {
          renderer.update(tree());
          await Promise.resolve();
        });
      },
    };
  }

  it("reads the new project's acceptance after a token refresh moves the project", async () => {
    const probe = await mountProbe();
    await waitForAssertion(() => {
      expect(currentResult.data).toBe(true);
    });

    projectId = 2;
    await probe.rerender();

    await waitForAssertion(() => {
      expect(mockAreDesktopBetaTermsAccepted).toHaveBeenCalledWith(2);
      expect(currentResult.data).toBe(false);
    });
  });

  it("errors instead of idling when the session has no scoped project", async () => {
    projectId = null;

    await mountProbe();

    await waitForAssertion(() => {
      expect(currentResult.isError).toBe(true);
    });
    expect(mockAreDesktopBetaTermsAccepted).not.toHaveBeenCalled();
  });
});
