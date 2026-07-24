import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type PropsWithChildren } from "react";
import { act, create } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { mockUseAuthStore, mockGetGithubRepositories, mockGetIntegrations } =
  vi.hoisted(() => ({
    mockUseAuthStore: vi.fn(),
    mockGetGithubRepositories: vi.fn(),
    mockGetIntegrations: vi.fn(),
  }));

vi.mock("@/features/auth", () => ({
  useAuthStore: mockUseAuthStore,
}));

vi.mock("../api", () => ({
  getGithubRepositories: mockGetGithubRepositories,
  getIntegrations: mockGetIntegrations,
}));

import { useRepositoryCacheStore } from "../stores/repositoryCacheStore";
import { useIntegrations } from "./useIntegrations";

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: PropsWithChildren) {
    return createElement(
      QueryClientProvider,
      { client: queryClient },
      children,
    );
  };
}

function renderTestHook<Result>(
  useHook: () => Result,
  wrapper:
    | ((props: PropsWithChildren) => ReturnType<typeof createElement>)
    | undefined,
) {
  let currentResult: Result;

  function HookProbe() {
    currentResult = useHook();
    return null;
  }

  function TestTree() {
    if (!wrapper) {
      return createElement(HookProbe);
    }

    const Wrapper = wrapper;
    return createElement(Wrapper, null, createElement(HookProbe));
  }

  let renderer: ReturnType<typeof create>;
  act(() => {
    renderer = create(createElement(TestTree));
  });

  return {
    result: {
      get current() {
        return currentResult;
      },
    },
    unmount() {
      act(() => {
        renderer.unmount();
      });
    },
  };
}

async function waitForAssertion(assertion: () => void): Promise<void> {
  const timeoutAt = Date.now() + 2_000;

  while (Date.now() < timeoutAt) {
    try {
      assertion();
      return;
    } catch (error) {
      await new Promise((resolve) => setTimeout(resolve, 10));
      if (Date.now() >= timeoutAt) {
        throw error;
      }
    }
  }
}

describe("useIntegrations", () => {
  beforeEach(() => {
    mockUseAuthStore.mockImplementation((selector) =>
      selector
        ? selector({
            projectId: 42,
            oauthAccessToken: "token",
          })
        : {
            projectId: 42,
            oauthAccessToken: "token",
          },
    );
    mockGetIntegrations.mockReset();
    mockGetGithubRepositories.mockReset();
    useRepositoryCacheStore.setState({ options: [], updatedAt: null });
  });

  it("keeps repositories from healthy integrations when one repository fetch fails", async () => {
    mockGetIntegrations.mockResolvedValueOnce([
      {
        id: 7,
        kind: "github",
        display_name: "Personal GitHub",
      },
      {
        id: 11,
        kind: "github",
        display_name: "PostHog",
      },
    ]);
    mockGetGithubRepositories
      .mockResolvedValueOnce(["annika/mobile-app"])
      .mockRejectedValueOnce(new Error("GitHub repos failed"));

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });
    const { result, unmount } = renderTestHook(
      () => useIntegrations(),
      createWrapper(queryClient),
    );

    await waitForAssertion(() => {
      expect(result.current.isLoading).toBe(false);
      expect(result.current.repositoryOptions).toEqual([
        {
          integrationId: 7,
          integrationLabel: "Personal GitHub",
          repository: "annika/mobile-app",
        },
      ]);
    });

    expect(result.current.repositoryWarning).toBe(
      "Some GitHub repositories could not be loaded. Pull to retry.",
    );
    expect(result.current.error).toBeNull();
    unmount();
  });

  it("surfaces integration fetch failures as blocking errors", async () => {
    mockGetIntegrations.mockRejectedValueOnce(
      new Error("Failed to fetch integrations"),
    );

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });
    const { result, unmount } = renderTestHook(
      () => useIntegrations(),
      createWrapper(queryClient),
    );

    await waitForAssertion(() => {
      expect(result.current.isLoading).toBe(false);
      expect(result.current.error).toBe("Failed to fetch integrations");
    });

    expect(result.current.repositoryOptions).toEqual([]);
    expect(result.current.repositoryWarning).toBeNull();
    unmount();
  });

  it("skips integration loading when repository requirements are disabled", async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });
    const { result, unmount } = renderTestHook(
      () => useIntegrations({ enabled: false }),
      createWrapper(queryClient),
    );

    expect(result.current.hasGithubIntegration).toBeNull();
    expect(result.current.githubIntegrations).toEqual([]);
    expect(result.current.repositories).toEqual([]);
    expect(result.current.repositoryOptions).toEqual([]);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();

    await act(async () => {
      await result.current.refetch();
    });

    expect(mockGetIntegrations).not.toHaveBeenCalled();
    expect(mockGetGithubRepositories).not.toHaveBeenCalled();
    unmount();
  });
});
