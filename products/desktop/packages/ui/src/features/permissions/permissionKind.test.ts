import {
  buildQuestionToolCallData,
  type QuestionItem,
} from "@posthog/agent/adapters/claude/questions/utils";
import { describe, expect, it } from "vitest";
import { isComposerPanelPermission, readQuestionCount } from "./permissionKind";
import type { PermissionToolCall } from "./types";

const questions: QuestionItem[] = [
  {
    question: "Which store should hold the collapsed state?",
    header: "Storage",
    options: [{ label: "Persisted" }, { label: "In memory" }],
  },
  {
    question: "What happens when the plan outgrows the column?",
    header: "Overflow",
    options: [{ label: "Scroll" }, { label: "Clip" }],
  },
];

describe("permissionKind", () => {
  it.each([
    {
      name: "a plan waiting for approval",
      toolCall: { toolCallId: "a", kind: "switch_mode" },
      expected: true,
    },
    {
      name: "a plan reported through codeToolKind",
      toolCall: { toolCallId: "b", _meta: { codeToolKind: "switch_mode" } },
      expected: true,
    },
    {
      name: "a shell command approval",
      toolCall: { toolCallId: "c", kind: "execute" },
      expected: false,
    },
    {
      name: "an edit approval",
      toolCall: { toolCallId: "d", _meta: { codeToolKind: "edit" } },
      expected: false,
    },
    {
      name: "a question set with no parsable questions",
      toolCall: { toolCallId: "e", kind: "question" },
      expected: false,
    },
  ])("routes $name to the card: $expected", ({ toolCall, expected }) => {
    expect(isComposerPanelPermission(toolCall as PermissionToolCall)).toBe(
      expected,
    );
  });

  it("routes a question set to the card and counts its questions", () => {
    const toolCall = buildQuestionToolCallData(questions) as PermissionToolCall;

    expect(isComposerPanelPermission(toolCall)).toBe(true);
    expect(readQuestionCount(toolCall)).toBe(2);
  });
});
