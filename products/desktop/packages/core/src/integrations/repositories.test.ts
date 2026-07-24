import { describe, expect, it } from "vitest";
import {
  combineGithubRepositories,
  combineRepositoryPicker,
  combineUserGithubRepositories,
  getIntegrationIdForRepo,
  isEmptyRepositoryMap,
  isRepoInIntegration,
  normalizeRepoKey,
  type RepositoryCacheAction,
  type RepositoryQueryResult,
  resolveEffectiveUserRepositoryMap,
  resolveUserRepositoryCacheAction,
  sameUserRepositoryMap,
  type TeamRepositoriesResult,
  type UserRepositoriesResult,
  type UserRepositoryCacheInputs,
  type UserRepositoryIntegrationRef,
} from "./repositories";

function result<T>(
  data: T | undefined,
  flags: Partial<Omit<RepositoryQueryResult<T>, "data">> = {},
): RepositoryQueryResult<T> {
  return {
    data,
    isPending: flags.isPending ?? false,
    isError: flags.isError ?? false,
    isRefetching: flags.isRefetching ?? false,
  };
}

describe("combineGithubRepositories", () => {
  it("builds a repo->integration map and keeps the first integration to claim a repo", () => {
    const results: RepositoryQueryResult<TeamRepositoriesResult>[] = [
      result({ integrationId: 1, repos: ["a/x", "a/y"] }),
      result({ integrationId: 2, repos: ["a/x", "a/z"] }),
    ];

    const combined = combineGithubRepositories(results);

    expect(combined.repositoryMap).toEqual({
      "a/x": 1,
      "a/y": 1,
      "a/z": 2,
    });
    expect(combined.isPending).toBe(false);
  });

  it("reports pending when any result is pending", () => {
    const combined = combineGithubRepositories([
      result<TeamRepositoriesResult>(undefined, { isPending: true }),
    ]);
    expect(combined.isPending).toBe(true);
  });
});

describe("combineUserGithubRepositories", () => {
  it("tracks reposByInstallationId and tallies failed installation ids", () => {
    const results: RepositoryQueryResult<UserRepositoriesResult>[] = [
      result({
        userIntegrationId: "u1",
        installationId: "i1",
        repos: ["a/x"],
      }),
      result<UserRepositoriesResult>(undefined, { isError: true }),
    ];

    const combined = combineUserGithubRepositories(results, ["i1", "i2"]);

    expect(combined.repositoryMap["a/x"]).toEqual({
      userIntegrationId: "u1",
      installationId: "i1",
    });
    expect(combined.reposByInstallationId).toEqual({ i1: ["a/x"] });
    expect(combined.failedInstallationIds).toEqual(["i2"]);
  });
});

describe("combineRepositoryPicker", () => {
  it("merges pages, derives hasMore/isRefreshing/isPending", () => {
    const combined = combineRepositoryPicker<UserRepositoryIntegrationRef>([
      {
        data: {
          ref: { userIntegrationId: "u1", installationId: "i1" },
          repositories: ["a/x"],
          hasMore: true,
        },
        isPending: false,
        isError: false,
        isRefetching: true,
      },
    ]);

    expect(Object.keys(combined.repositoryMap)).toEqual(["a/x"]);
    expect(combined.hasMore).toBe(true);
    expect(combined.isRefreshing).toBe(true);
  });
});

describe("repo key helpers", () => {
  it("normalizes case", () => {
    expect(normalizeRepoKey("Acme/Repo")).toBe("acme/repo");
  });

  it("looks up integration id case-insensitively", () => {
    expect(getIntegrationIdForRepo({ "a/x": 5 }, "A/X")).toBe(5);
  });

  it("treats empty repo key as in-integration", () => {
    expect(isRepoInIntegration({}, "")).toBe(true);
    expect(isRepoInIntegration({ "a/x": 1 }, "A/X")).toBe(true);
    expect(isRepoInIntegration({}, "a/x")).toBe(false);
  });
});

const ref: UserRepositoryIntegrationRef = {
  userIntegrationId: "u1",
  installationId: "i1",
};

describe("isEmptyRepositoryMap", () => {
  it("detects empty and non-empty maps", () => {
    expect(isEmptyRepositoryMap({})).toBe(true);
    expect(isEmptyRepositoryMap({ "a/x": ref })).toBe(false);
  });
});

describe("sameUserRepositoryMap", () => {
  it("compares by content, not reference", () => {
    expect(
      sameUserRepositoryMap({ "a/x": { ...ref } }, { "a/x": { ...ref } }),
    ).toBe(true);
  });

  it("differs on size, missing keys or changed refs", () => {
    expect(sameUserRepositoryMap({ "a/x": ref }, {})).toBe(false);
    expect(sameUserRepositoryMap({ "a/x": ref }, { "a/y": ref })).toBe(false);
    expect(
      sameUserRepositoryMap(
        { "a/x": ref },
        { "a/x": { userIntegrationId: "u2", installationId: "i1" } },
      ),
    ).toBe(false);
  });
});

describe("resolveUserRepositoryCacheAction", () => {
  const cases: Array<{
    name: string;
    inputs: UserRepositoryCacheInputs;
    expected: RepositoryCacheAction;
  }> = [
    {
      name: "skips while integrations are pending",
      inputs: {
        integrationsPending: true,
        reposPending: false,
        reposErrored: false,
        hasIntegrations: true,
        liveRepositoryMap: { "a/x": ref },
        cachedRepositoryMap: {},
      },
      expected: "skip",
    },
    {
      name: "clears when there are no integrations and a cache exists",
      inputs: {
        integrationsPending: false,
        reposPending: false,
        reposErrored: false,
        hasIntegrations: false,
        liveRepositoryMap: {},
        cachedRepositoryMap: { "a/x": ref },
      },
      expected: "clear",
    },
    {
      name: "skips clearing when there are no integrations and no cache",
      inputs: {
        integrationsPending: false,
        reposPending: false,
        reposErrored: false,
        hasIntegrations: false,
        liveRepositoryMap: {},
        cachedRepositoryMap: {},
      },
      expected: "skip",
    },
    {
      name: "skips while repos are pending",
      inputs: {
        integrationsPending: false,
        reposPending: true,
        reposErrored: false,
        hasIntegrations: true,
        liveRepositoryMap: {},
        cachedRepositoryMap: { "a/x": ref },
      },
      expected: "skip",
    },
    {
      name: "keeps the cache when an errored fetch returns empty",
      inputs: {
        integrationsPending: false,
        reposPending: false,
        reposErrored: true,
        hasIntegrations: true,
        liveRepositoryMap: {},
        cachedRepositoryMap: { "a/x": ref },
      },
      expected: "skip",
    },
    {
      name: "clears a stale cache when a clean fetch returns empty",
      inputs: {
        integrationsPending: false,
        reposPending: false,
        reposErrored: false,
        hasIntegrations: true,
        liveRepositoryMap: {},
        cachedRepositoryMap: { "a/x": ref },
      },
      expected: "clear",
    },
    {
      name: "skips when a clean empty fetch matches an empty cache",
      inputs: {
        integrationsPending: false,
        reposPending: false,
        reposErrored: false,
        hasIntegrations: true,
        liveRepositoryMap: {},
        cachedRepositoryMap: {},
      },
      expected: "skip",
    },
    {
      name: "skips when live data equals the cache by content",
      inputs: {
        integrationsPending: false,
        reposPending: false,
        reposErrored: false,
        hasIntegrations: true,
        liveRepositoryMap: { "a/x": { ...ref } },
        cachedRepositoryMap: { "a/x": { ...ref } },
      },
      expected: "skip",
    },
    {
      name: "writes when live data differs from the cache",
      inputs: {
        integrationsPending: false,
        reposPending: false,
        reposErrored: false,
        hasIntegrations: true,
        liveRepositoryMap: { "a/y": ref },
        cachedRepositoryMap: { "a/x": ref },
      },
      expected: "write",
    },
  ];

  it.each(cases)("$name", ({ inputs, expected }) => {
    expect(resolveUserRepositoryCacheAction(inputs)).toBe(expected);
  });
});

describe("resolveEffectiveUserRepositoryMap", () => {
  const cached = { "a/y": ref };
  const live = { "a/x": ref };

  it("uses live data when not loading even if a cache exists", () => {
    const result = resolveEffectiveUserRepositoryMap({
      liveLoading: false,
      liveRepositoryMap: {},
      cachedRepositoryMap: cached,
    });
    expect(result.servingFromCache).toBe(false);
    expect(result.effectiveRepositoryMap).toEqual({});
  });

  it("serves the cache while loading with an empty live map", () => {
    const result = resolveEffectiveUserRepositoryMap({
      liveLoading: true,
      liveRepositoryMap: {},
      cachedRepositoryMap: cached,
    });
    expect(result.servingFromCache).toBe(true);
    expect(result.effectiveRepositoryMap).toBe(cached);
  });

  it("prefers live data once it arrives mid-load", () => {
    const result = resolveEffectiveUserRepositoryMap({
      liveLoading: true,
      liveRepositoryMap: live,
      cachedRepositoryMap: cached,
    });
    expect(result.servingFromCache).toBe(false);
    expect(result.effectiveRepositoryMap).toBe(live);
  });

  it("does not serve from cache when both maps are empty", () => {
    const result = resolveEffectiveUserRepositoryMap({
      liveLoading: true,
      liveRepositoryMap: {},
      cachedRepositoryMap: {},
    });
    expect(result.servingFromCache).toBe(false);
    expect(result.effectiveRepositoryMap).toEqual({});
  });
});
