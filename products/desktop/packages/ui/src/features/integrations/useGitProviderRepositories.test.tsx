import "reflect-metadata";
import { GitProviderService } from "@posthog/core/integrations/gitProviderService";
import { RepositoriesService } from "@posthog/core/integrations/repositoriesService";
import type { Integration } from "@posthog/core/integrations/selectors";
import { clearAuthScopedQueries } from "@posthog/ui/features/auth/authQueries";
import {
  ANONYMOUS_AUTH_STATE,
  useAuthStore,
} from "@posthog/ui/features/auth/store";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useIntegrationStore } from "./store";
import { useGitProviderRepositories } from "./useGitProviderRepositories";
import { useGithubRepositoryQueries } from "./useIntegrations";

const mocks = vi.hoisted(() => ({
  client: null as unknown,
  service: null as unknown,
  queryClient: null as unknown,
  getIntegrations: vi.fn(),
  getGithubRepositories: vi.fn(),
  refreshTeamRepository: vi.fn(),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => mocks.client,
}));
vi.mock("@posthog/di/react", () => ({ useService: () => mocks.service }));
vi.mock("@posthog/di/container", () => ({
  resolveService: () => mocks.queryClient,
}));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => true,
}));
vi.mock("@posthog/ui/shell/logger", () => ({
  logger: { scope: () => ({ error: vi.fn() }) },
}));

const github: Integration = {
  id: 1,
  kind: "github",
  display_name: "Example GitHub",
};
const gitlab: Integration = {
  id: 2,
  kind: "gitlab",
  config: { path_with_namespace: "example/gitlab" },
};
let queryClient: QueryClient;
const authenticated = {
  ...ANONYMOUS_AUTH_STATE,
  status: "authenticated" as const,
  bootstrapComplete: true,
  cloudRegion: "us" as const,
  currentProjectId: 1,
};

function wrapper({ children }: PropsWithChildren) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  mocks.queryClient = queryClient;
  mocks.client = {
    getIntegrations: mocks.getIntegrations,
    getGithubRepositories: mocks.getGithubRepositories,
  };
  mocks.service = new GitProviderService(
    new RepositoriesService({
      refreshTeamRepository: mocks.refreshTeamRepository,
      refreshUserRepository: vi.fn(),
    }),
  );
  mocks.getIntegrations.mockResolvedValue([github, gitlab]);
  mocks.getGithubRepositories.mockResolvedValue(["example/github"]);
  mocks.refreshTeamRepository.mockResolvedValue(undefined);
  useAuthStore.getState().setAuthState(authenticated);
  useIntegrationStore.getState().setIntegrations([], null);
});

afterEach(() => {
  cleanup();
  queryClient.clear();
});

describe("useGitProviderRepositories", () => {
  it("keeps integration loading and failure distinct from an empty list and retries on refresh", async () => {
    mocks.getIntegrations
      .mockRejectedValueOnce(new Error("Unavailable"))
      .mockResolvedValue([]);
    const { result } = renderHook(useGitProviderRepositories, { wrapper });
    expect(result.current.isPending).toBe(true);
    await waitFor(() => expect(result.current.isError).toBe(true));
    act(() => result.current.refetch());
    await waitFor(() => expect(result.current.isError).toBe(false));
    expect(result.current.isPending).toBe(false);
    expect(result.current.data.repositories).toEqual([]);
  });

  it("shares each GitHub query with the existing repository list", async () => {
    let finish!: (repos: string[]) => void;
    mocks.getGithubRepositories.mockReturnValue(
      new Promise<string[]>((resolve) => {
        finish = resolve;
      }),
    );
    const { result } = renderHook(
      () => ({
        combined: useGitProviderRepositories(),
        existing: useGithubRepositoryQueries([github]),
      }),
      { wrapper },
    );
    await waitFor(() =>
      expect(result.current.combined.data.repositories).toHaveLength(1),
    );
    expect(result.current.combined.data.repositories[0].provider).toBe(
      "gitlab",
    );
    expect(mocks.getGithubRepositories).toHaveBeenCalledTimes(1);
    act(() => finish(["example/github"]));
    await waitFor(() =>
      expect(result.current.combined.data.repositories).toHaveLength(2),
    );
    expect(result.current.existing[0].data?.repos).toEqual(["example/github"]);
    expect(mocks.getGithubRepositories).toHaveBeenCalledTimes(1);
  });

  it("retries a failed connection without hiding healthy repositories", async () => {
    queryClient.setDefaultOptions({ queries: { retry: 1, retryDelay: 0 } });
    mocks.getGithubRepositories
      .mockRejectedValueOnce(new Error("Unavailable"))
      .mockResolvedValue(["example/recovered"]);
    const { result } = renderHook(useGitProviderRepositories, { wrapper });
    await waitFor(() =>
      expect(
        result.current.data.repositories.map(
          (repository) => repository.fullName,
        ),
      ).toEqual(["example/recovered", "example/gitlab"]),
    );
    expect(mocks.getGithubRepositories).toHaveBeenCalledTimes(2);
    expect(result.current.data.failedConnections).toEqual([]);
  });

  it("refreshes the server snapshot before showing the new GitHub repository list", async () => {
    let repositories = ["example/before"];
    mocks.getGithubRepositories.mockImplementation(async () => repositories);
    mocks.refreshTeamRepository.mockImplementation(async () => {
      repositories = ["example/after"];
    });
    const { result } = renderHook(useGitProviderRepositories, { wrapper });
    await waitFor(() =>
      expect(result.current.data.repositories[0]?.fullName).toBe(
        "example/before",
      ),
    );
    act(() => result.current.refetch());
    await waitFor(() =>
      expect(result.current.data.repositories[0]?.fullName).toBe(
        "example/after",
      ),
    );
  });

  it.each(["first", "second", "both"] as const)(
    "keeps successful refreshes and reports the error when the %s GitHub connection fails",
    async (failure) => {
      const otherGithub: Integration = { ...github, id: 3 };
      const repositories = new Map([
        [github.id, ["example/first-before"]],
        [otherGithub.id, ["example/second-before"]],
      ]);
      mocks.getIntegrations.mockResolvedValue([github, otherGithub, gitlab]);
      mocks.getGithubRepositories.mockImplementation(async (id: number) =>
        repositories.get(id),
      );
      mocks.refreshTeamRepository.mockImplementation(async (id: number) => {
        if (
          failure === "both" ||
          (failure === "first" ? id === github.id : id === otherGithub.id)
        ) {
          throw new Error("Unavailable");
        }
        repositories.set(id, [
          id === github.id ? "example/first-after" : "example/second-after",
        ]);
      });
      const { result } = renderHook(useGitProviderRepositories, { wrapper });
      await waitFor(() =>
        expect(result.current.data.repositories).toHaveLength(3),
      );

      act(() => result.current.refetch());

      await waitFor(() => expect(result.current.hasRefreshError).toBe(true));
      await waitFor(() =>
        expect(
          result.current.data.repositories.map(
            (repository) => repository.fullName,
          ),
        ).toEqual([
          failure === "second" ? "example/first-after" : "example/first-before",
          failure === "first"
            ? "example/second-after"
            : "example/second-before",
          "example/gitlab",
        ]),
      );
      expect(result.current.isError).toBe(false);
    },
  );

  it.each(["project", "region", "account"] as const)(
    "drops previous integration data after a %s change when the new request fails",
    async (change) => {
      const { result } = renderHook(useGitProviderRepositories, { wrapper });
      await waitFor(() =>
        expect(result.current.data.repositories).toHaveLength(2),
      );
      mocks.getIntegrations.mockRejectedValue(new Error("Unavailable"));
      if (change === "account") {
        act(() => {
          mocks.client = null;
          useAuthStore
            .getState()
            .setAuthState({ ...ANONYMOUS_AUTH_STATE, bootstrapComplete: true });
          clearAuthScopedQueries();
        });
        expect(useIntegrationStore.getState().integrations).toEqual([]);
        expect(result.current.data.repositories).toEqual([]);
      }
      act(() => {
        mocks.client = {
          getIntegrations: mocks.getIntegrations,
          getGithubRepositories: mocks.getGithubRepositories,
        };
        useAuthStore.getState().setAuthState({
          ...authenticated,
          ...(change === "project" ? { currentProjectId: 2 } : {}),
          ...(change === "region" ? { cloudRegion: "eu" as const } : {}),
        });
      });
      expect(result.current.data.repositories).toEqual([]);
      await waitFor(() => expect(result.current.isError).toBe(true));
      expect(result.current.data.repositories).toEqual([]);
      expect(useIntegrationStore.getState().integrations).toEqual([]);
    },
  );
});
