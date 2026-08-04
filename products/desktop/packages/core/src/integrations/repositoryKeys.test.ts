import { describe, expect, it } from "vitest";
import {
  integrationKeys,
  teamRepositoryRefreshKeys,
  userGithubIntegrationKeys,
  userRepositoryRefreshKeys,
} from "./repositoryKeys";

describe("repositoryKeys", () => {
  it("namespaces team repository keys", () => {
    expect(integrationKeys.repositories(7)).toEqual([
      "integrations",
      "repositories",
      7,
    ]);
  });

  it("namespaces user repository keys", () => {
    expect(userGithubIntegrationKeys.repositories("inst")).toEqual([
      "user-github-integrations",
      "repositories",
      "inst",
    ]);
  });

  it("derives team refetch keys with an exact key per integration plus the picker", () => {
    expect(teamRepositoryRefreshKeys([1, 2])).toEqual([
      { queryKey: ["integrations", "repositories", 1], exact: true },
      { queryKey: ["integrations", "repositories", 2], exact: true },
      { queryKey: ["integrations", "repository-picker"], exact: false },
    ]);
  });

  it("derives only the picker key when there are no integrations", () => {
    expect(teamRepositoryRefreshKeys([])).toEqual([
      { queryKey: ["integrations", "repository-picker"], exact: false },
    ]);
  });

  it("derives user refetch keys with an exact key per installation plus the picker", () => {
    expect(userRepositoryRefreshKeys(["a"])).toEqual([
      {
        queryKey: ["user-github-integrations", "repositories", "a"],
        exact: true,
      },
      {
        queryKey: ["user-github-integrations", "repository-picker"],
        exact: false,
      },
    ]);
  });
});
