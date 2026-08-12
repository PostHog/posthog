import { describe, expect, it, vi } from "vitest";
import type { RepositoriesClient } from "./identifiers";
import { RepositoriesService } from "./repositoriesService";

function makeClient(): RepositoriesClient {
  return {
    refreshTeamRepository: vi.fn().mockResolvedValue([]),
    refreshUserRepository: vi.fn().mockResolvedValue([]),
  };
}

describe("RepositoriesService", () => {
  it("fans out a team refresh across every integration id", async () => {
    const client = makeClient();
    const service = new RepositoriesService(client);

    await service.refreshTeamRepositories([1, 2, 3]);

    expect(client.refreshTeamRepository).toHaveBeenCalledTimes(3);
    expect(client.refreshTeamRepository).toHaveBeenCalledWith(1);
    expect(client.refreshTeamRepository).toHaveBeenCalledWith(2);
    expect(client.refreshTeamRepository).toHaveBeenCalledWith(3);
  });

  it("fans out a user refresh across every installation id", async () => {
    const client = makeClient();
    const service = new RepositoriesService(client);

    await service.refreshUserRepositories(["a", "b"]);

    expect(client.refreshUserRepository).toHaveBeenCalledTimes(2);
    expect(client.refreshUserRepository).toHaveBeenCalledWith("a");
    expect(client.refreshUserRepository).toHaveBeenCalledWith("b");
  });

  it("skips the team client call when there are no integrations", async () => {
    const client = makeClient();
    const service = new RepositoriesService(client);

    await service.refreshTeamRepositories([]);

    expect(client.refreshTeamRepository).not.toHaveBeenCalled();
  });

  it("skips the user client call when there are no installations", async () => {
    const client = makeClient();
    const service = new RepositoriesService(client);

    await service.refreshUserRepositories([]);

    expect(client.refreshUserRepository).not.toHaveBeenCalled();
  });

  it("propagates a refresh failure from any integration", async () => {
    const client = makeClient();
    (client.refreshTeamRepository as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce([])
      .mockRejectedValueOnce(new Error("boom"));
    const service = new RepositoriesService(client);

    await expect(service.refreshTeamRepositories([1, 2])).rejects.toThrow(
      "boom",
    );
  });

  it("refreshes team repos then returns the per-integration refetch keys", async () => {
    const client = makeClient();
    const service = new RepositoriesService(client);

    const keys = await service.refreshTeamRepositoriesAndKeys([1, 2]);

    expect(client.refreshTeamRepository).toHaveBeenCalledTimes(2);
    expect(keys).toEqual([
      { queryKey: ["integrations", "repositories", 1], exact: true },
      { queryKey: ["integrations", "repositories", 2], exact: true },
      { queryKey: ["integrations", "repository-picker"], exact: false },
    ]);
  });

  it("refreshes user repos then returns the per-installation refetch keys", async () => {
    const client = makeClient();
    const service = new RepositoriesService(client);

    const keys = await service.refreshUserRepositoriesAndKeys(["a", "b"]);

    expect(client.refreshUserRepository).toHaveBeenCalledTimes(2);
    expect(keys).toEqual([
      {
        queryKey: ["user-github-integrations", "repositories", "a"],
        exact: true,
      },
      {
        queryKey: ["user-github-integrations", "repositories", "b"],
        exact: true,
      },
      {
        queryKey: ["user-github-integrations", "repository-picker"],
        exact: false,
      },
    ]);
  });
});
