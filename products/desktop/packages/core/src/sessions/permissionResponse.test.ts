import type { PermissionRequest } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  formatPermissionAnswerPrompt,
  isOtherPermissionOption,
  planPermissionResponse,
} from "./permissionResponse";

function makePermission(
  options: Array<{
    optionId: string;
    kind?: string;
    _meta?: Record<string, unknown>;
  }>,
  toolCallKind?: string,
): PermissionRequest & { toolCallId: string } {
  return {
    taskRunId: "run-1",
    receivedAt: 0,
    toolCallId: "tool-1",
    toolCall: toolCallKind ? { kind: toolCallKind } : undefined,
    options,
  } as unknown as PermissionRequest & { toolCallId: string };
}

describe("isOtherPermissionOption", () => {
  it("recognizes both canonical other ids", () => {
    expect(isOtherPermissionOption("_other")).toBe(true);
    expect(isOtherPermissionOption("other")).toBe(true);
    expect(isOtherPermissionOption("allow")).toBe(false);
  });
});

describe("planPermissionResponse", () => {
  it("flags allow_always upgrade when option is allow_always and not a mode switch", () => {
    const permission = makePermission([
      { optionId: "allow", kind: "allow_always" },
    ]);
    const plan = planPermissionResponse(permission, "allow");
    expect(plan.applyAllowAlwaysUpgrade).toBe(true);
  });

  it("does not upgrade for allow_always when tool call is a mode switch", () => {
    const permission = makePermission(
      [{ optionId: "allow", kind: "allow_always" }],
      "switch_mode",
    );
    const plan = planPermissionResponse(permission, "allow");
    expect(plan.applyAllowAlwaysUpgrade).toBe(false);
  });

  it("responds with custom input for the other option", () => {
    const permission = makePermission([{ optionId: "_other" }]);
    const plan = planPermissionResponse(permission, "_other", "do this");
    expect(plan.respondWithCustomInput).toBe(true);
    expect(plan.resendPromptText).toBeNull();
  });

  it("responds with custom input when option meta opts in", () => {
    const permission = makePermission([
      { optionId: "feedback", _meta: { customInput: true } },
    ]);
    const plan = planPermissionResponse(permission, "feedback", "more detail");
    expect(plan.respondWithCustomInput).toBe(true);
    expect(plan.resendPromptText).toBeNull();
  });

  it("re-sends custom input as a prompt for a plain option", () => {
    const permission = makePermission([{ optionId: "allow" }]);
    const plan = planPermissionResponse(permission, "allow", "follow up");
    expect(plan.respondWithCustomInput).toBe(false);
    expect(plan.resendPromptText).toBe("follow up");
  });

  it("responds plainly with no custom input", () => {
    const permission = makePermission([{ optionId: "allow" }]);
    const plan = planPermissionResponse(permission, "allow");
    expect(plan.respondWithCustomInput).toBe(false);
    expect(plan.resendPromptText).toBeNull();
  });
});

describe("formatPermissionAnswerPrompt", () => {
  const questionPermission = (questions: Array<{ question: string }>) =>
    ({
      taskRunId: "run-1",
      receivedAt: 0,
      toolCall: {
        toolCallId: "tool-1",
        _meta: { codeToolKind: "question", questions },
      },
      options: [
        { optionId: "option_0", name: "MIT", kind: "allow_once" },
        { optionId: "option_1", name: "Apache 2.0", kind: "allow_once" },
      ],
    }) as unknown as PermissionRequest;

  it("quotes each question above its answer", () => {
    const prompt = formatPermissionAnswerPrompt(
      questionPermission([{ question: "Which license should I use?" }]),
      "option_0",
      undefined,
      { "Which license should I use?": "MIT" },
    );
    expect(prompt).toBe("MIT");
  });

  it("carries every entry of a multi-question answers map", () => {
    const prompt = formatPermissionAnswerPrompt(
      questionPermission([{ question: "Q1?" }, { question: "Q2?" }]),
      "option_0",
      undefined,
      { "Q1?": "A1", "Q2?": "A2" },
    );
    expect(prompt).toBe("1. A1\n2. A2");
  });

  it("falls back to the picked option label when no answers map is sent", () => {
    const prompt = formatPermissionAnswerPrompt(
      questionPermission([{ question: "Which license should I use?" }]),
      "option_1",
    );
    expect(prompt).toBe("Apache 2.0");
  });

  it("uses free-text custom input for a question", () => {
    const prompt = formatPermissionAnswerPrompt(
      questionPermission([{ question: "Which license should I use?" }]),
      "_other",
      "BSD, actually",
    );
    expect(prompt).toBe("BSD, actually");
  });

  it.each([
    ["plain approval", "allow", undefined],
    ["plain rejection with feedback", "reject", "not like this"],
  ])(
    "returns null for %s so no resume run is spun",
    (_caseName, optionId, customInput) => {
      const approval = makePermission([
        { optionId: "allow", kind: "allow_once" },
      ]);
      expect(
        formatPermissionAnswerPrompt(approval, optionId, customInput),
      ).toBeNull();
    },
  );
});
