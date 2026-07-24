import { describe, expect, it } from "vitest";
import {
  type PromptRecallAction,
  type PromptRecallDirection,
  type PromptRecallResult,
  promptRecallStep,
  resolvePromptRecall,
} from "./composerPromptRecall";

const ids = ["m1", "m2", "m3"];

describe("promptRecallStep", () => {
  it.each<{
    name: string;
    currentId: string | null;
    direction: PromptRecallDirection;
    expected: PromptRecallAction | null;
  }>([
    {
      name: "up with no recall in progress starts fresh on the newest prompt",
      currentId: null,
      direction: -1,
      expected: { kind: "recall", id: "m3", fresh: true },
    },
    {
      name: "up from the middle recalls the previous prompt",
      currentId: "m2",
      direction: -1,
      expected: { kind: "recall", id: "m1", fresh: false },
    },
    {
      name: "up at the oldest prompt stays on it",
      currentId: "m1",
      direction: -1,
      expected: { kind: "recall", id: "m1", fresh: false },
    },
    {
      name: "up with an unknown current id starts fresh on the newest prompt",
      currentId: "gone",
      direction: -1,
      expected: { kind: "recall", id: "m3", fresh: true },
    },
    {
      name: "down with no recall in progress does nothing",
      currentId: null,
      direction: 1,
      expected: null,
    },
    {
      name: "down from the middle recalls the next prompt",
      currentId: "m2",
      direction: 1,
      expected: { kind: "recall", id: "m3", fresh: false },
    },
    {
      name: "down at the newest prompt exits recall",
      currentId: "m3",
      direction: 1,
      expected: { kind: "exit" },
    },
    {
      name: "down with an unknown current id does nothing",
      currentId: "gone",
      direction: 1,
      expected: null,
    },
  ])("$name", ({ currentId, direction, expected }) => {
    expect(promptRecallStep(ids, currentId, direction)).toEqual(expected);
  });

  it.each<{
    name: string;
    currentId: string | null;
    direction: PromptRecallDirection;
    expected: PromptRecallAction | null;
  }>([
    {
      name: "up with no recall in progress recalls it fresh",
      currentId: null,
      direction: -1,
      expected: { kind: "recall", id: "m1", fresh: true },
    },
    {
      name: "up while on it stays on it",
      currentId: "m1",
      direction: -1,
      expected: { kind: "recall", id: "m1", fresh: false },
    },
    {
      name: "down while on it exits recall",
      currentId: "m1",
      direction: 1,
      expected: { kind: "exit" },
    },
  ])(
    "with a single sent prompt, $name",
    ({ currentId, direction, expected }) => {
      expect(promptRecallStep(["m1"], currentId, direction)).toEqual(expected);
    },
  );

  it.each<{ direction: PromptRecallDirection }>([
    { direction: -1 },
    { direction: 1 },
  ])(
    "returns null when no prompts were sent (direction $direction)",
    ({ direction }) => {
      expect(promptRecallStep([], null, direction)).toBeNull();
    },
  );
});

describe("resolvePromptRecall", () => {
  const messages = [
    { id: "m1", content: "first prompt" },
    { id: "m2", content: "second prompt" },
  ];

  it.each<{
    name: string;
    currentId: string | null;
    direction: PromptRecallDirection;
    expectedResult: PromptRecallResult | null;
    expectedNextId: string | null;
  }>([
    {
      name: "recalls the newest prompt fresh and tracks its id",
      currentId: null,
      direction: -1,
      expectedResult: { kind: "recall", text: "second prompt", fresh: true },
      expectedNextId: "m2",
    },
    {
      name: "steps to an older prompt and tracks its id",
      currentId: "m2",
      direction: -1,
      expectedResult: { kind: "recall", text: "first prompt", fresh: false },
      expectedNextId: "m1",
    },
    {
      name: "exits at the newest prompt and clears the tracked id",
      currentId: "m2",
      direction: 1,
      expectedResult: { kind: "exit" },
      expectedNextId: null,
    },
    {
      name: "stays inert on down outside recall and keeps the id",
      currentId: null,
      direction: 1,
      expectedResult: null,
      expectedNextId: null,
    },
    {
      name: "stays inert on a stale id and keeps it",
      currentId: "gone",
      direction: 1,
      expectedResult: null,
      expectedNextId: "gone",
    },
  ])("$name", ({ currentId, direction, expectedResult, expectedNextId }) => {
    expect(resolvePromptRecall(messages, currentId, direction)).toEqual({
      result: expectedResult,
      nextId: expectedNextId,
    });
  });

  it("returns null and keeps the id when no prompts were sent", () => {
    expect(resolvePromptRecall([], null, -1)).toEqual({
      result: null,
      nextId: null,
    });
  });

  it.each<{ name: string; content: string }>([
    {
      name: "a channel context block",
      content:
        '<channel_context channel="growth">CONTEXT.md body</channel_context>\n\nfix the bug',
    },
    {
      name: "a canvas instructions block",
      content:
        "<canvas_generation_instructions>authoring rules</canvas_generation_instructions>\n\nfix the bug",
    },
    {
      name: "a custom instructions block",
      content:
        "fix the bug\n\n<user_custom_instructions>be terse</user_custom_instructions>",
    },
    {
      name: "a trailing attachment summary",
      content: "fix the bug\n\nAttached files: screenshot.png",
    },
    {
      name: "several injected blocks at once",
      content:
        '<channel_context channel="growth">CONTEXT.md body</channel_context>\n\nfix the bug\n\n<user_custom_instructions>be terse</user_custom_instructions>',
    },
  ])("strips $name from the recalled text", ({ content }) => {
    expect(resolvePromptRecall([{ id: "m1", content }], null, -1)).toEqual({
      result: { kind: "recall", text: "fix the bug", fresh: true },
      nextId: "m1",
    });
  });
});
