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
