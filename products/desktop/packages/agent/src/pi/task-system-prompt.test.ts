import { describe, expect, it } from "vitest";
import { buildTaskSystemPrompt } from "./task-system-prompt";

describe("buildTaskSystemPrompt", () => {
  it("builds durable local task instructions", () => {
    const prompt = buildTaskSystemPrompt({
      projectId: 42,
      apiHost: "https://us.posthog.com",
      taskId: "task-123",
      cwd: "/tmp/task-123",
      environment: "local",
      customInstructions: "Keep the patch small.",
      additionalDirectories: ["/tmp/a&b", "/tmp/<shared>"],
      channelMode: true,
    });

    expect(prompt).toContain("use project 42 on https://us.posthog.com");
    expect(prompt).toContain("This is task task-123");
    expect(prompt).toContain("Generated-By: PostHog Desktop");
    expect(prompt).toContain("Task-Id: task-123");
    expect(prompt).toContain("Keep the patch small.");
    expect(prompt).toContain("<directory>/tmp/a&amp;b</directory>");
    expect(prompt).toContain("<directory>/tmp/&lt;shared&gt;</directory>");
    expect(prompt).toContain("## Channel task");
    expect(prompt).toContain("Your working directory is `/tmp/task-123`");
  });

  it("describes the repository tools only when the harness registers them", () => {
    const context = {
      projectId: 42,
      apiHost: "https://us.posthog.com",
      taskId: "task-123",
      cwd: "/tmp/task-123",
      environment: "local",
      channelMode: true,
    } as const;

    expect(buildTaskSystemPrompt(context)).not.toContain("list_repos");
    expect(buildTaskSystemPrompt(context, { repositoryTools: true })).toContain(
      "call `list_repos` to find it",
    );
  });

  it("includes signed commit attribution instructions for cloud tasks", () => {
    const prompt = buildTaskSystemPrompt({
      projectId: 42,
      apiHost: "https://us.posthog.com",
      taskId: "task-123",
      cwd: "/tmp/workspace",
      environment: "cloud",
      additionalInstructions: "Use the existing pull request.",
    });

    expect(prompt).toContain("git_signed_commit");
    expect(prompt).toContain("Generated-By: PostHog Desktop");
    expect(prompt).toContain("Task-Id: task-123");
    expect(prompt).not.toContain('git commit -m "$(cat');
    expect(prompt).toContain("Use the existing pull request.");
  });
});
