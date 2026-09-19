import { describe, expect, it } from "vitest";
import {
  type PreviewConfigOption,
  selectModelFromOptions,
} from "./reportTaskCreation";

const RESTRICTED_META = { "posthog.code/restrictedModel": true };

function modelOption(
  currentValue: string,
  available: string[],
  restricted: string[] = [],
): PreviewConfigOption {
  return {
    id: "model",
    category: "model",
    type: "select",
    currentValue,
    options: available.map((value) => ({
      value,
      ...(restricted.includes(value) ? { _meta: RESTRICTED_META } : {}),
    })),
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
    {
      // Restricted models stay in the option list so the picker can draw them
      // locked. Headless flows draw no picker, so honouring a persisted
      // restricted model here is what 403s the run before any work happens.
      name: "rejects a preferred model the org's plan does not allow",
      options: [
        modelOption(
          "claude-sonnet-4-8",
          ["claude-opus-5", "claude-sonnet-4-8"],
          ["claude-opus-5"],
        ),
      ],
      preferredModel: "claude-opus-5",
      expected: "claude-sonnet-4-8",
    },
    {
      name: "rejects a restricted preferred model nested in a labelled group",
      options: [
        {
          id: "model",
          category: "model",
          type: "select",
          currentValue: "claude-sonnet-4-8",
          options: [
            { options: [{ value: "claude-sonnet-4-8" }] },
            {
              options: [{ value: "claude-opus-5", _meta: RESTRICTED_META }],
            },
          ],
        } satisfies PreviewConfigOption,
      ],
      preferredModel: "claude-opus-5",
      expected: "claude-sonnet-4-8",
    },
    {
      // The server default is not trustworthy either — downgrade through
      // pickAllowedModel rather than handing the gateway a restricted model.
      name: "downgrades when the server default is restricted too",
      options: [
        modelOption(
          "claude-opus-5",
          ["claude-opus-5", "claude-opus-4-8", "claude-sonnet-4-8"],
          ["claude-opus-5", "claude-opus-4-8"],
        ),
      ],
      preferredModel: "claude-opus-5",
      expected: "claude-sonnet-4-8",
    },
    {
      // Nothing better to offer, so the gateway keeps the last word.
      name: "keeps the server default when no model is allowed",
      options: [
        modelOption("claude-opus-5", ["claude-opus-5"], ["claude-opus-5"]),
      ],
      preferredModel: undefined,
      expected: "claude-opus-5",
    },
    {
      // A model outside the gateway catalog isn't in the options at all;
      // pickAllowedModel leaves it alone rather than inventing a downgrade.
      name: "keeps a server default that is not in the option list",
      options: [modelOption("custom-model", ["claude-sonnet-4-8"])],
      preferredModel: undefined,
      expected: "custom-model",
    },
  ])("$name", ({ options, preferredModel, expected }) => {
    expect(selectModelFromOptions(options, preferredModel)).toBe(expected);
  });
});
