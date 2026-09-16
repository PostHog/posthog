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

  it("reads the new project's acceptance after a token refresh moves the project", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    let currentResult: ReturnType<typeof useDesktopBetaTerms>;

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
    // already seen, so reusing it would never pick the new project up.
    const tree = () => createElement(Wrapper, null, createElement(HookProbe));
    let renderer!: ReturnType<typeof create>;
    await act(async () => {
      renderer = create(tree());
      await Promise.resolve();
    });
    await waitForAssertion(() => {
      expect(currentResult.data).toBe(true);
    });

    projectId = 2;
    await act(async () => {
      renderer.update(tree());
      await Promise.resolve();
    });

    await waitForAssertion(() => {
      expect(mockAreDesktopBetaTermsAccepted).toHaveBeenCalledWith(2);
      expect(currentResult.data).toBe(false);
    });
  });
});
