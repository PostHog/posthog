import { describe, expect, it, vi } from "vitest";
import {
  rewriteLocalSkillCommandPrompt,
  tryExecuteCodeCommand,
} from "./commands";
import type { EditorAvailableCommand } from "./types";

const toastError = vi.hoisted(() => vi.fn());
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: toastError, success: vi.fn() },
}));

const commands: EditorAvailableCommand[] = [
  {
    name: "local-test-skill",
    description: "Local user skill",
    localSkill: {
      name: "local-test-skill",
      source: "user",
      path: "/Users/example/.claude/skills/local-test-skill",
    },
  },
];

describe("message editor commands", () => {
  it("rewrites local skill slash commands to skill tags", () => {
    expect(rewriteLocalSkillCommandPrompt("/local-test-skill", commands)).toBe(
      '<skill name="local-test-skill" source="user" path="/Users/example/.claude/skills/local-test-skill" />',
    );
  });

  it("preserves local skill arguments after the skill tag", () => {
    expect(
      rewriteLocalSkillCommandPrompt(
        "/local-test-skill with context",
        commands,
      ),
    ).toBe(
      '<skill name="local-test-skill" source="user" path="/Users/example/.claude/skills/local-test-skill" /> with context',
    );
  });

  it("does not rewrite unknown commands", () => {
    expect(
      rewriteLocalSkillCommandPrompt("/feedback looks good", commands),
    ).toBe(null);
  });
});

describe("/btw command", () => {
  const baseContext = {
    taskId: "task-1",
    repoPath: "/tmp/repo",
    session: null,
    taskRun: null,
  };

  it("routes the question to askSideQuestion and reports handled", async () => {
    toastError.mockClear();
    const askSideQuestion = vi.fn().mockReturnValue(true);
    const handled = await tryExecuteCodeCommand("/btw what changed here?", {
      ...baseContext,
      askSideQuestion,
    });
    expect(handled).toBe(true);
    expect(askSideQuestion).toHaveBeenCalledWith("what changed here?");
    expect(toastError).not.toHaveBeenCalled();
  });

  it("toasts when a side question is already pending", async () => {
    toastError.mockClear();
    const askSideQuestion = vi.fn().mockReturnValue(false);
    const handled = await tryExecuteCodeCommand("/btw and another thing?", {
      ...baseContext,
      askSideQuestion,
    });
    expect(handled).toBe(true);
    expect(toastError).toHaveBeenCalledWith(
      "Wait for your last side question to finish first",
    );
  });

  it("toasts on an empty question without calling askSideQuestion", async () => {
    toastError.mockClear();
    const askSideQuestion = vi.fn();
    const handled = await tryExecuteCodeCommand("/btw", {
      ...baseContext,
      askSideQuestion,
    });
    expect(handled).toBe(true);
    expect(askSideQuestion).not.toHaveBeenCalled();
    expect(toastError).toHaveBeenCalledWith("Add a question after /btw");
  });

  it("toasts when the session doesn't support side questions", async () => {
    toastError.mockClear();
    const handled = await tryExecuteCodeCommand("/btw is this supported?", {
      ...baseContext,
      askSideQuestion: undefined,
    });
    expect(handled).toBe(true);
    expect(toastError).toHaveBeenCalledWith(
      "Side questions aren't supported for this session yet.",
    );
  });

  it("leaves non-command text unhandled", async () => {
    expect(await tryExecuteCodeCommand("btw not a command", baseContext)).toBe(
      false,
    );
  });
});
