import type { Task } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  canApplyTitleFromPrompts,
  decideTitleGeneration,
  formatPromptsForTitleInput,
  getFallbackTaskTitle,
  isAutoTitleLocked,
  isPlaceholderTaskTitle,
  REGENERATE_INTERVAL,
  selectPromptsForTitle,
} from "./chatTitle";

function task(overrides: Partial<Task>): Task {
  return {
    title: "Fix login",
    description: "Fix login",
    title_manually_set: false,
    ...overrides,
  } as Task;
}

describe("isPlaceholderTaskTitle", () => {
  it("treats an empty title as a placeholder", () => {
    expect(isPlaceholderTaskTitle({ title: "  ", description: "x" })).toBe(
      true,
    );
  });

  it("treats a title equal to the description fallback as a placeholder", () => {
    expect(
      isPlaceholderTaskTitle({ title: "Fix login", description: "Fix login" }),
    ).toBe(true);
  });

  it("treats a custom title as not a placeholder", () => {
    expect(
      isPlaceholderTaskTitle({ title: "Custom", description: "Fix login" }),
    ).toBe(false);
  });
});

describe("isAutoTitleLocked", () => {
  it("is false when the title was not manually set", () => {
    expect(isAutoTitleLocked(task({ title_manually_set: false }))).toBe(false);
  });

  it("is false when manually set but the title still matches the fallback", () => {
    expect(
      isAutoTitleLocked(task({ title_manually_set: true, title: "Fix login" })),
    ).toBe(false);
  });

  it("is true when manually set to a custom title", () => {
    expect(
      isAutoTitleLocked(task({ title_manually_set: true, title: "Custom" })),
    ).toBe(true);
  });
});

describe("getFallbackTaskTitle", () => {
  it("falls back to Untitled when the description is empty", () => {
    expect(getFallbackTaskTitle("   ")).toBe("Untitled");
  });
});

describe("decideTitleGeneration", () => {
  it("generates from the first prompt", () => {
    const decision = decideTitleGeneration({
      promptCount: 1,
      lastGeneratedAtCount: 0,
      initialDescriptionHandled: false,
      task: { title: "Custom", description: "d" },
    });
    expect(decision.shouldGenerateFromPrompts).toBe(true);
  });

  it("does not regenerate from the first prompt when the description was handled", () => {
    const decision = decideTitleGeneration({
      promptCount: 1,
      lastGeneratedAtCount: 0,
      initialDescriptionHandled: true,
      task: { title: "Custom", description: "d" },
    });
    expect(decision.shouldGenerateFromPrompts).toBe(false);
  });

  it("regenerates every REGENERATE_INTERVAL prompts", () => {
    const decision = decideTitleGeneration({
      promptCount: 1 + REGENERATE_INTERVAL,
      lastGeneratedAtCount: 1,
      initialDescriptionHandled: false,
      task: { title: "Custom", description: "d" },
    });
    expect(decision.shouldGenerateFromPrompts).toBe(true);
  });

  it("generates from a placeholder task description before any prompt", () => {
    const decision = decideTitleGeneration({
      promptCount: 0,
      lastGeneratedAtCount: 0,
      initialDescriptionHandled: false,
      task: { title: "Fix login", description: "Fix login" },
    });
    expect(decision.shouldGenerateFromTaskDescription).toBe(true);
  });

  it.each([
    {
      name: "skips a catch-up fire when the title is locked and a summary exists",
      promptCount: 1 + REGENERATE_INTERVAL,
      lastGeneratedAtCount: 0,
      initialDescriptionHandled: false,
      titleLocked: true,
      hasSummary: true,
      expected: false,
    },
    {
      name: "runs a catch-up fire when no summary exists yet",
      promptCount: 1 + REGENERATE_INTERVAL,
      lastGeneratedAtCount: 0,
      initialDescriptionHandled: false,
      titleLocked: true,
      hasSummary: false,
      expected: true,
    },
    {
      name: "runs a catch-up fire when the title is not locked",
      promptCount: 1 + REGENERATE_INTERVAL,
      lastGeneratedAtCount: 0,
      initialDescriptionHandled: false,
      titleLocked: false,
      hasSummary: true,
      expected: true,
    },
    {
      name: "still refreshes the summary at the interval while locked",
      promptCount: 1 + REGENERATE_INTERVAL,
      lastGeneratedAtCount: 1,
      initialDescriptionHandled: false,
      titleLocked: true,
      hasSummary: true,
      expected: true,
    },
    {
      name: "still generates on the first prompt while locked",
      promptCount: 1,
      lastGeneratedAtCount: 0,
      initialDescriptionHandled: false,
      titleLocked: true,
      hasSummary: false,
      expected: true,
    },
    {
      name: "treats a description-handled interval fire as organic while locked",
      promptCount: REGENERATE_INTERVAL,
      lastGeneratedAtCount: 0,
      initialDescriptionHandled: true,
      titleLocked: true,
      hasSummary: true,
      expected: true,
    },
  ])(
    "$name",
    ({
      promptCount,
      lastGeneratedAtCount,
      initialDescriptionHandled,
      titleLocked,
      hasSummary,
      expected,
    }) => {
      const decision = decideTitleGeneration({
        promptCount,
        lastGeneratedAtCount,
        initialDescriptionHandled,
        task: { title: "Custom", description: "d" },
        isTitleLocked: () => titleLocked,
        hasSummary,
      });
      expect(decision.shouldGenerateFromPrompts).toBe(expected);
    },
  );
});

describe("canApplyTitleFromPrompts", () => {
  it("allows the first-prompt fire to write the title", () => {
    expect(
      canApplyTitleFromPrompts(1, { title: "Custom", description: "d" }),
    ).toBe(true);
  });

  it("blocks later fires from rewriting a real title", () => {
    expect(
      canApplyTitleFromPrompts(1 + REGENERATE_INTERVAL, {
        title: "Fix login bug",
        description: "the login page 500s",
      }),
    ).toBe(false);
  });

  it("allows later fires to replace a placeholder title", () => {
    expect(
      canApplyTitleFromPrompts(1 + REGENERATE_INTERVAL, {
        title: "Fix login",
        description: "Fix login",
      }),
    ).toBe(true);
  });
});

describe("selectPromptsForTitle", () => {
  it("returns all prompts on the first prompt", () => {
    expect(selectPromptsForTitle(["a"], 1)).toEqual(["a"]);
  });

  it("returns the last REGENERATE_INTERVAL prompts otherwise", () => {
    const prompts = Array.from({ length: 10 }, (_, i) => `p${i}`);
    expect(selectPromptsForTitle(prompts, 10)).toHaveLength(
      REGENERATE_INTERVAL,
    );
  });
});

describe("formatPromptsForTitleInput", () => {
  it("numbers prompts from one", () => {
    expect(formatPromptsForTitleInput(["a", "b"])).toBe("1. a\n2. b");
  });
});
