import { describe, expect, it } from "vitest";
import {
  buildGithubRepositoriesPatch,
  effectiveGithubSourceRepos,
  githubIssuesSchemaNames,
  githubIssuesSchemasToEnable,
  githubSourceIntegrationId,
} from "./githubSourceRepos";

describe("effectiveGithubSourceRepos", () => {
  it.each([
    [
      "multi-repo source",
      { repositories: ["acme/a", "acme/b"], repository: "acme/a" },
      ["acme/a", "acme/b"],
    ],
    ["legacy single repo", { repository: "acme/a" }, ["acme/a"]],
    [
      "empty repositories falls back to legacy",
      { repositories: [], repository: "acme/a" },
      ["acme/a"],
    ],
    ["nothing configured", { auth_method: {} }, []],
    ["missing job inputs", undefined, []],
  ])("%s", (_name, jobInputs, expected) => {
    expect(effectiveGithubSourceRepos(jobInputs)).toEqual(expected);
  });
});

describe("buildGithubRepositoriesPatch", () => {
  it("sends only the repositories list, deduplicated", () => {
    expect(
      buildGithubRepositoriesPatch(["acme/a", "acme/b", "acme/a"]),
    ).toEqual({ job_inputs: { repositories: ["acme/a", "acme/b"] } });
  });
});

describe("githubIssuesSchemaNames", () => {
  it.each([
    [
      "qualifies and lowercases every repository",
      ["Acme/A", "acme/b"],
      undefined,
      ["acme/a.issues", "acme/b.issues"],
    ],
    [
      "keeps the pre-multi-repo repository bare",
      ["acme/a", "acme/b"],
      { repository: "Acme/A" },
      ["issues", "acme/b.issues"],
    ],
    ["no repositories", [], undefined, []],
  ])("%s", (_name, repos, jobInputs, expected) => {
    expect(githubIssuesSchemaNames(repos, jobInputs)).toEqual(expected);
  });
});

describe("githubIssuesSchemasToEnable", () => {
  const schemas = [
    { id: "1", name: "issues", should_sync: true, sync_type: "full_refresh" },
    { id: "2", name: "acme/b.issues", should_sync: false, sync_type: null },
    { id: "3", name: "acme/b.commits", should_sync: false, sync_type: null },
    {
      id: "4",
      name: "acme/c.issues",
      should_sync: true,
      sync_type: "incremental",
    },
  ];

  it.each([
    ["a repository whose issues are off", ["acme/b"], ["2"]],
    ["a repository already replicating in full", ["acme/a"], []],
    ["a repository on the wrong sync type", ["acme/c"], ["4"]],
    ["a repository with no rows yet", ["acme/d"], []],
  ])("%s", (_name, repos, expectedIds) => {
    const source = { job_inputs: { repository: "acme/a" }, schemas };
    expect(githubIssuesSchemasToEnable(repos, source).map((s) => s.id)).toEqual(
      expectedIds,
    );
  });
});

describe("githubSourceIntegrationId", () => {
  it.each([
    ["oauth source", { auth_method: { github_integration_id: 7 } }, 7],
    [
      "id stored as a string",
      { auth_method: { github_integration_id: "7" } },
      7,
    ],
    [
      "personal access token source",
      { auth_method: { selection: "pat" } },
      null,
    ],
    ["missing job inputs", undefined, null],
  ])("%s", (_name, jobInputs, expected) => {
    expect(githubSourceIntegrationId(jobInputs)).toBe(expected);
  });
});
