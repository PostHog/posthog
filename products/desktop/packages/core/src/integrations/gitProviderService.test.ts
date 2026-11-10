import { describe, expect, it, vi } from "vitest";
import { GitProviderService } from "./gitProviderService";
import { RepositoriesService } from "./repositoriesService";
import type { Integration } from "./selectors";

const integrations: Integration[] = [
  { id: 1, kind: "github", display_name: "Example" },
  { id: 2, kind: "github", display_name: "Unavailable" },
  { id: 3, kind: "gitlab", config: { path_with_namespace: "example/desktop" } },
  { id: 4, kind: "slack" },
];

function service() {
  return new GitProviderService(
    new RepositoriesService({
      refreshTeamRepository: vi.fn().mockResolvedValue(undefined),
      refreshUserRepository: vi.fn().mockResolvedValue(undefined),
    }),
  );
}

describe("GitProviderService", () => {
  it.each(["pending", "error"] as const)(
    "keeps healthy repositories when a GitHub connection is %s",
    (status) => {
      const result = service().combineRepositories(
        integrations,
        ["github", "gitlab"],
        [
          {
            data: { integrationId: 1, repos: ["Example/project"] },
            isPending: false,
            isError: false,
            isRefetching: false,
          },
          {
            data: undefined,
            isPending: status === "pending",
            isError: status === "error",
            isRefetching: false,
          },
        ],
      );
      expect(
        result.repositories.map((repository) => repository.fullName),
      ).toEqual(["example/project", "example/desktop"]);
      expect(
        result.failedConnections.map((connection) => connection.integrationId),
      ).toEqual(status === "error" ? [2] : []);
      expect(
        result.pendingConnections.map((connection) => connection.integrationId),
      ).toEqual(status === "pending" ? [2] : []);
    },
  );

  it("excludes GitLab repositories when the provider is disabled", () => {
    const result = service().combineRepositories(integrations, ["github"], []);
    expect(
      result.connections.map((connection) => connection.integrationId),
    ).toEqual([1, 2]);
    expect(result.repositories).toEqual([]);
  });

  it("refreshes the GitHub server cache before returning the query keys", async () => {
    const refreshTeamRepository = vi.fn().mockResolvedValue(undefined);
    const provider = new GitProviderService(
      new RepositoriesService({
        refreshTeamRepository,
        refreshUserRepository: vi.fn(),
      }),
    );
    const { keys, errors } = await provider.refreshRepositories(integrations);
    expect(refreshTeamRepository.mock.calls).toEqual([[1], [2]]);
    expect(errors).toEqual([]);
    expect(keys).toContainEqual({
      queryKey: ["integrations", "repositories", 1],
      exact: false,
    });
  });
});
