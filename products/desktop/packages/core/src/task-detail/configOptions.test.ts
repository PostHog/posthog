import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { modelHarnessMeta } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  flattenConfigValues,
  harnessForModelValue,
  modelOptionForHarness,
  syntheticPiModelSelection,
} from "./configOptions";

const groupedModelOption = {
  id: "model",
  name: "Model",
  type: "select",
  category: "model",
  currentValue: "claude-opus-5",
  description: "",
  options: [
    {
      group: "anthropic",
      name: "Anthropic",
      options: [
        {
          value: "claude-opus-5",
          name: "Opus 5",
          _meta: modelHarnessMeta("claude"),
        },
      ],
    },
    {
      group: "openai",
      name: "OpenAI",
      options: [
        { value: "gpt-5.5", name: "GPT-5.5", _meta: modelHarnessMeta("codex") },
      ],
    },
  ],
} as SessionConfigOption;

const flatUnstampedOption = {
  id: "model",
  name: "Model",
  type: "select",
  category: "model",
  currentValue: "claude-opus-5",
  description: "",
  options: [
    { value: "claude-opus-5", name: "Opus 5" },
    { value: "gpt-5.5", name: "GPT-5.5" },
  ],
} as SessionConfigOption;

describe("harnessForModelValue", () => {
  it.each([
    {
      label: "reads the harness stamped on a grouped option",
      option: groupedModelOption,
      value: "gpt-5.5",
      expected: "codex",
    },
    {
      label: "falls back to the id shape when nothing is stamped",
      option: flatUnstampedOption,
      value: "gpt-5.5",
      expected: "codex",
    },
    {
      label: "returns undefined for a model the option does not offer",
      option: groupedModelOption,
      value: "gpt-4o",
      expected: undefined,
    },
  ])("$label", ({ option, value, expected }) => {
    expect(harnessForModelValue(option, value)).toBe(expected);
  });

  it("returns undefined without an option", () => {
    expect(harnessForModelValue(undefined, "gpt-5.5")).toBeUndefined();
  });
});

describe("syntheticPiModelSelection", () => {
  it.each([
    {
      label: "takes the display name from the option",
      value: "gpt-5.5",
      expected: "GPT-5.5",
    },
    {
      label: "falls back to a formatted id for a model the option lacks",
      value: "claude-opus-4-8",
      expected: "Claude Opus 4.8",
    },
  ])("$label", ({ value, expected }) => {
    expect(syntheticPiModelSelection(groupedModelOption, value)).toMatchObject({
      provider: "posthog",
      id: value,
      name: expected,
      thinkingLevels: [],
    });
  });
});

describe("modelOptionForHarness", () => {
  it.each([
    { adapter: "claude" as const, expected: ["claude-opus-5"] },
    { adapter: "codex" as const, expected: ["gpt-5.5"] },
  ])(
    "keeps only $adapter models from a grouped list",
    ({ adapter, expected }) => {
      const narrowed = modelOptionForHarness(groupedModelOption, adapter);
      expect(flattenConfigValues(narrowed as SessionConfigOption)).toEqual(
        expected,
      );
    },
  );

  it("leaves a single-harness list alone", () => {
    expect(modelOptionForHarness(flatUnstampedOption, "claude")).toBe(
      flatUnstampedOption,
    );
  });
});
