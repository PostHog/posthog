import { describe, expect, it } from "vitest";
import {
  type PreviewConfigOption,
  selectModelFromOptions,
} from "./reportTaskCreation";

function modelOption(
  currentValue: string,
  available: string[],
): PreviewConfigOption {
  return {
    id: "model",
    category: "model",
    type: "select",
    currentValue,
    options: available.map((value) => ({ value })),
  };
}

describe("selectModelFromOptions", () => {
  it.each([
    {
      name: "returns the server default when no preferred model is given",
      options: [modelOption("claude-opus-4-8", ["claude-opus-4-8"])],
      preferredModel: undefined,
      expected: "claude-opus-4-8",
    },
    {
      name: "honours the preferred model when the gateway still offers it",
      options: [
        modelOption("claude-opus-4-8", [
          "claude-opus-4-8",
          "claude-sonnet-4-6",
        ]),
      ],
      preferredModel: "claude-sonnet-4-6",
      expected: "claude-sonnet-4-6",
    },
    {
      // The persisted model (e.g. a de-listed fable) is not in the available
      // options, so it must not be returned — otherwise the run 403s.
      name: "falls back to the server default when the preferred model is no longer offered",
      options: [modelOption("claude-opus-4-8", ["claude-opus-4-8"])],
      preferredModel: "claude-fable-5",
      expected: "claude-opus-4-8",
    },
    {
      name: "ignores an empty string preferred model",
      options: [modelOption("claude-opus-4-8", ["claude-opus-4-8"])],
      preferredModel: "",
      expected: "claude-opus-4-8",
    },
    {
      name: "ignores a null preferred model",
      options: [modelOption("claude-opus-4-8", ["claude-opus-4-8"])],
      preferredModel: null,
      expected: "claude-opus-4-8",
    },
    {
      // The gateway can return models wrapped in labelled groups; a preferred
      // model nested inside a group must still count as available.
      name: "honours a preferred model nested in a labelled group",
      options: [
        {
          id: "model",
          category: "model",
          type: "select",
          currentValue: "claude-opus-4-8",
          options: [
            { options: [{ value: "claude-opus-4-8" }] },
            { options: [{ value: "claude-sonnet-4-6" }] },
          ],
        } satisfies PreviewConfigOption,
      ],
      preferredModel: "claude-sonnet-4-6",
      expected: "claude-sonnet-4-6",
    },
    {
      name: "returns undefined when there is no model option",
      options: [
        { id: "mode", category: "mode", type: "select", currentValue: "plan" },
      ] satisfies PreviewConfigOption[],
      preferredModel: "claude-opus-4-8",
      expected: undefined,
    },
  ])("$name", ({ options, preferredModel, expected }) => {
    expect(selectModelFromOptions(options, preferredModel)).toBe(expected);
  });
});
