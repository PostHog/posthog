import { AI_FEEDBACK_TEXT_MAX_LENGTH } from "@posthog/core/analytics/aiFeedback";
import { describe, expect, it, vi } from "vitest";
import {
  getCodeCommandInputError,
  rewriteLocalSkillCommandPrompt,
  tryExecuteCodeCommand,
} from "./commands";
import type { EditorAvailableCommand } from "./types";

const toastError = vi.hoisted(() => vi.fn());
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: toastError, success: vi.fn() },
}));

const track = vi.hoisted(() => vi.fn());
vi.mock("../../shell/analytics", () => ({ track }));

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

describe("feedback commands", () => {
  const context = {
    taskId: "task-1",
    repoPath: null,
    session: {
      taskRunId: "run-1",
      events: [{}, {}],
    },
    taskRun: null,
  };
  const expectedContext = {
    $ai_session_id: "task-1",
    $ai_trace_id: null,
    ai_product: "posthog_code",
    task_id: "task-1",
    task_run_id: "run-1",
  };

  it("captures /bad with a comment as a quality metric plus feedback text", async () => {
    track.mockClear();
    expect(await tryExecuteCodeCommand("/bad wrong file", context)).toBe(true);
    expect(track).toHaveBeenCalledWith(
      "$ai_metric",
      expect.objectContaining({
        ...expectedContext,
        $ai_metric_name: "quality",
        $ai_metric_value: "bad",
      }),
    );
    expect(track).toHaveBeenCalledWith(
      "$ai_feedback",
      expect.objectContaining({
        ...expectedContext,
        $ai_feedback_text: "wrong file",
        event_count: 2,
      }),
    );
    expect(track).toHaveBeenCalledTimes(2);
  });

  it("rejects /feedback without a comment and captures nothing", async () => {
    track.mockClear();
    toastError.mockClear();
    expect(await tryExecuteCodeCommand("/feedback", context)).toBe(true);
    expect(track).not.toHaveBeenCalled();
    expect(toastError).toHaveBeenCalledWith(
      expect.stringContaining("Add a comment after /feedback"),
    );
  });

  it("rejects an over-limit comment pre-submit and reports the counts", () => {
    const oversized = "x".repeat(AI_FEEDBACK_TEXT_MAX_LENGTH + 234);
    const error = getCodeCommandInputError(`/feedback ${oversized}`);
    expect(error).toContain("4,234 characters");
    expect(error).toContain("the limit is 4,000");
  });

  it.each([
    ["/feedback", true],
    ["/feedback  ", true],
    ["/btw", true],
    ["/feedback add a diff view", false],
    [`/good ${"x".repeat(AI_FEEDBACK_TEXT_MAX_LENGTH + 1)}`, true],
    [`/feedback ${"x".repeat(AI_FEEDBACK_TEXT_MAX_LENGTH)}`, false],
    ["/good", false],
    ["/bad no comment needed", false],
    ["plain message", false],
  ])("pre-submit input check for %j blocks=%s", (text, blocks) => {
    const error = getCodeCommandInputError(text);
    expect(error !== null).toBe(blocks);
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
