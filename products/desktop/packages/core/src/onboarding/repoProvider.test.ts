import { describe, expect, it } from "vitest";
import {
  inferRepositoryProvider,
  repoMatchesGitHubRepos,
  toDetectedRepo,
} from "./repoProvider";

describe("inferRepositoryProvider", () => {
  it("returns local when there is no remote", () => {
    expect(inferRepositoryProvider(undefined)).toBe("local");
  });

  it("classifies github and gitlab hosts", () => {
    expect(inferRepositoryProvider("git@github.com:acme/app.git")).toBe(
      "github",
    );
    expect(inferRepositoryProvider("https://gitlab.com/acme/app.git")).toBe(
      "gitlab",
    );
  });

  it("returns none for other hosts", () => {
    expect(inferRepositoryProvider("https://bitbucket.org/acme/app")).toBe(
      "none",
    );
  });
});

describe("toDetectedRepo", () => {
  it("returns null for empty input", () => {
    expect(toDetectedRepo(null)).toBeNull();
    expect(toDetectedRepo(undefined)).toBeNull();
  });

  it("shapes the detect result into a DetectedRepo", () => {
    expect(
      toDetectedRepo({
        organization: "acme",
        repository: "app",
        remote: "git@github.com:acme/app.git",
        branch: "main",
      }),
    ).toEqual({
      organization: "acme",
      repository: "app",
      fullName: "acme/app",
      remote: "git@github.com:acme/app.git",
      branch: "main",
    });
  });

  it("coerces null remote/branch to undefined", () => {
    const repo = toDetectedRepo({
      organization: "acme",
      repository: "app",
      remote: null,
      branch: null,
    });
    expect(repo?.remote).toBeUndefined();
    expect(repo?.branch).toBeUndefined();
  });
});

describe("repoMatchesGitHubRepos", () => {
  const detected = {
    organization: "acme",
    repository: "app",
    fullName: "acme/app",
  };

  it("returns false without a detected repo or repositories", () => {
    expect(repoMatchesGitHubRepos(null, ["acme/app"])).toBe(false);
    expect(repoMatchesGitHubRepos(detected, [])).toBe(false);
  });

  it("matches case-insensitively", () => {
    expect(repoMatchesGitHubRepos(detected, ["ACME/App"])).toBe(true);
    expect(repoMatchesGitHubRepos(detected, ["other/repo"])).toBe(false);
  });
});
