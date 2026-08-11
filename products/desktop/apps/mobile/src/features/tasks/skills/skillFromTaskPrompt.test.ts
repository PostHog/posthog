import { describe, expect, it } from "vitest";
import { buildCreateSkillFromTaskPrompt } from "./skillFromTaskPrompt";

describe("buildCreateSkillFromTaskPrompt", () => {
  it("names the MCP tool the agent must call", () => {
    expect(buildCreateSkillFromTaskPrompt()).toContain("create_llm_skill");
  });

  it("states the server's name and description limits", () => {
    const prompt = buildCreateSkillFromTaskPrompt();
    expect(prompt).toContain("at most 64 characters");
    expect(prompt).toContain("at most 4096 characters");
    expect(prompt).toContain("lowercase letters, numbers, and hyphens only");
  });

  it("asks for a generalized method rather than task specifics", () => {
    const prompt = buildCreateSkillFromTaskPrompt();
    expect(prompt).toContain("Generalize");
    expect(prompt).toContain("strip out this task's specific names");
  });

  it("asks the agent to report the resulting skill name", () => {
    expect(buildCreateSkillFromTaskPrompt()).toContain(
      "reply with the skill name you created",
    );
  });

  it("gives the agent an out when nothing generalizes", () => {
    expect(buildCreateSkillFromTaskPrompt()).toContain("create nothing");
  });

  it.each<[string | null | undefined, string]>([
    ["Fix the flaky login test", 'this task ("Fix the flaky login test")'],
    ["  Padded title  ", 'this task ("Padded title")'],
    ["", "this task and the conversation above"],
    ["   ", "this task and the conversation above"],
    [null, "this task and the conversation above"],
    [undefined, "this task and the conversation above"],
  ])("renders the subject for title %s", (taskTitle, expected) => {
    expect(buildCreateSkillFromTaskPrompt({ taskTitle })).toContain(expected);
  });

  it("omits the title clause entirely when no options are passed", () => {
    expect(buildCreateSkillFromTaskPrompt()).toContain(
      "Turn this task and the conversation above into a reusable team skill.",
    );
  });
});
