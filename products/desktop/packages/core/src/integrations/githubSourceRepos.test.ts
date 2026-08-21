import { describe, expect, it } from "vitest";
import {
  buildGithubRepositoriesPatch,
  effectiveGithubSourceRepos,
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
