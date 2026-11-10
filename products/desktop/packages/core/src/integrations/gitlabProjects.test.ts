import { describe, expect, it } from "vitest";
import {
  combineGitlabProjects,
  type GitlabProjectsResult,
} from "./gitlabProjects";

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
