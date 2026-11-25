import { describe, expect, it } from "vitest";
import { CloudTaskPrompt } from "./cloud";

describe("GitLab follow-up prompt", () => {
  it("fetches a tracking ref before checking out a merge request branch", () => {
    const prompt = new CloudTaskPrompt({
      apiUrl: "https://example.com",
      projectId: 1,
      taskId: "task",
      taskRepositories: [],
      hasGithubToken: false,
      repositoryAttached: true,
      shouldAutoPublish: true,
      gitProvider: "gitlab",
      storeSkills: [] as never,
    }).buildDetectedPrContext(
      "https://gitlab.com/example/repo/-/merge_requests/1",
    );
    expect(prompt).toContain("git remote set-branches --add origin <branch>");
    expect(prompt).toContain(
      "+refs/heads/<branch>:refs/remotes/origin/<branch>",
    );
    expect(prompt).toContain(
      "git checkout -b <branch> --track origin/<branch>",
    );
  });
});

describe("auto-published security fixes", () => {
  it.each([
    { gitProvider: "github", repositoryAttached: true, prUrl: null },
    { gitProvider: "github", repositoryAttached: false, prUrl: null },
    {
      gitProvider: "github",
      repositoryAttached: true,
      prUrl: "https://github.com/example/repo/pull/1",
    },
    { gitProvider: "gitlab", repositoryAttached: true, prUrl: null },
    {
      gitProvider: "gitlab",
      repositoryAttached: true,
      prUrl: "https://gitlab.com/example/repo/-/merge_requests/1",
    },
  ] as const)(
    "asks before publishing a security fix ($gitProvider, repo attached: $repositoryAttached, existing: $prUrl)",
    ({ gitProvider, repositoryAttached, prUrl }) => {
      const prompt = new CloudTaskPrompt({
        apiUrl: "https://example.com",
        projectId: 1,
        taskId: "task",
        taskRepositories: [],
        hasGithubToken: true,
        repositoryAttached,
        shouldAutoPublish: true,
        gitProvider,
        storeSkills: [] as never,
      }).buildCloudSystemPrompt(prUrl, "footer");
      expect(prompt).toContain(
        "Security fixes are the exception to publishing without asking.",
      );
    },
  );

  it.each([
    ["github", "https://github.com/example/repo/pull/1"],
    ["gitlab", "https://gitlab.com/example/repo/-/merge_requests/1"],
  ] as const)(
    "keeps the rule in the %s follow-up override",
    (gitProvider, prUrl) => {
      const context = new CloudTaskPrompt({
        apiUrl: "https://example.com",
        projectId: 1,
        taskId: "task",
        taskRepositories: [],
        hasGithubToken: true,
        repositoryAttached: true,
        shouldAutoPublish: true,
        gitProvider,
        storeSkills: [] as never,
      }).buildDetectedPrContext(prUrl);
      expect(context).toContain("Except for a security fix");
    },
  );
});
