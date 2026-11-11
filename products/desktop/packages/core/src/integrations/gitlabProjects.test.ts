import { describe, expect, it } from "vitest";
import {
  combineGitlabProjects,
  findGitlabProjectForRepository,
  type GitlabProjectsResult,
} from "./gitlabProjects";
import type { Integration } from "./selectors";

const result = (
  integrationId: number,
  missingScopes: string[],
): GitlabProjectsResult => ({
  integrationId,
  response: {
    projects: [
      {
        id: 7,
        path_with_namespace: "acme/platform/api",
        web_url: "https://gitlab.example.com/acme/platform/api",
        default_branch: "main",
      },
    ],
    missing_scopes: missingScopes,
    token_expires_at: null,
  },
});

describe("combineGitlabProjects", () => {
  it.each([
    [
      "the first connection has every scope",
      [result(1, []), result(2, ["api"])],
      1,
    ],
    [
      "only the second connection has every scope",
      [result(1, ["api"]), result(2, [])],
      2,
    ],
    [
      "neither connection has every scope",
      [result(1, ["api"]), result(2, ["api"])],
      1,
    ],
  ])(
    "lists a shared project once when %s",
    (_, results, expectedIntegrationId) => {
      expect(combineGitlabProjects(results)).toMatchObject({
        projects: ["acme/platform/api"],
        integrationIdByProject: { "acme/platform/api": expectedIntegrationId },
      });
    },
  );
});

describe("findGitlabProjectForRepository", () => {
  const integrations = [
    { id: 4, kind: "gitlab", config: { path_with_namespace: "acme/web" } },
    {
      id: 9,
      kind: "gitlab",
      config: { path_with_namespace: "Acme/Platform/API" },
    },
  ] as Integration[];

  it.each([
    [
      "a nested project, any case",
      "acme/platform/api",
      { project: "Acme/Platform/API", integrationId: 9 },
    ],
    ["a GitHub repository", "acme/github-only", null],
    ["no repository", undefined, null],
  ])("resolves %s", (_, repository, expected) => {
    expect(findGitlabProjectForRepository(repository, integrations)).toEqual(
      expected,
    );
  });
});
