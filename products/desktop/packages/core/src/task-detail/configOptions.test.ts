import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { modelHarnessMeta } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { harnessForModelValue } from "./configOptions";

const groupedModelOption = {
  id: "model",
  name: "Model",
  type: "select",
  category: "model",
  currentValue: "claude-opus-5",
  description: "",
  options: [
    {
      group: "claude",
      name: "Claude Code",
      options: [
        {
          value: "claude-opus-5",
          name: "Opus 5",
          _meta: modelHarnessMeta("claude"),
        },
      ],
    },
    {
      group: "codex",
      name: "Codex",
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
      label: "reads the current harness's own group too",
      option: groupedModelOption,
      value: "claude-opus-5",
      expected: "claude",
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
