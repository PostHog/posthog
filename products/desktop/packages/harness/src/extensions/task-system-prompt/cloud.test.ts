import { describe, expect, it } from "vitest";
import { CloudTaskPrompt } from "./cloud";

describe("CloudTaskPrompt", () => {
  const baseOptions = {
    apiUrl: "https://us.posthog.com",
    isAutomatedOrigin: true,
    isSlack: false,
    projectId: 2,
    hasGithubToken: true,
    shouldAutoPublish: false,
    slackArtifactDelivery: null,
    slackChartDelivery: false,
    storeSkillsInstalledCount: 0,
    taskId: "task-123",
  };

  // A repo-less run answers a question and stops, so the shared "before you end a turn" line is
  // the only thing asking it for a summary and a chat answer does not read as ending a turn.
  // Dropping this nudge is what leaves a discussion run's summary empty.
  it("asks a repo-less run to recap the conversation in the task summary", () => {
    const prompt = new CloudTaskPrompt({
      ...baseOptions,
      repositoryAttached: false,
      taskRepositories: [],
    }).buildCloudSystemPrompt();

    expect(prompt).toContain("# Cloud Task Execution — No Repository Mode");
    expect(prompt).toContain("Answering the question ends the turn");
    expect(prompt).toContain(
      "what was asked, what you found, and what is still open",
    );
  });

  it("keeps the shared summary block on a run that has a repository", () => {
    const prompt = new CloudTaskPrompt({
      ...baseOptions,
      repositoryAttached: true,
      taskRepositories: ["PostHog/posthog"],
    }).buildCloudSystemPrompt();

    expect(prompt).not.toContain("Answering the question ends the turn");
    expect(prompt).toContain("including a turn that only answers a question");
  });
});
