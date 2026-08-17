import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { EFFORT_LEVELS } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  applyConfigChange,
  clampEffortToAvailable,
  deriveInitialConfig,
  type PreviewSettingsSnapshot,
  pickPreferredRunSelection,
} from "./previewConfig";

function toggleOption(
  id: "context_window" | "fast",
  currentValue: string,
  values: string[],
): SessionConfigOption {
  return {
    id,
    name: id === "context_window" ? "Context Window" : "Fast Mode",
    type: "select",
    category: id === "context_window" ? "_context_window" : "_fast_mode",
    currentValue,
    description: "",
    options: values.map((value) => ({ value, name: value })),
  } as SessionConfigOption;
}

const baseSettings: PreviewSettingsSnapshot = {
  defaultInitialTaskMode: "plan",
  lastUsedInitialTaskMode: undefined,
  defaultReasoningEffort: "high",
  lastUsedReasoningEffort: undefined,
};

describe("clampEffortToAvailable", () => {
  it.each([
    {
      label: "returns the desired level when it is available",
      desired: "high",
      available: ["low", "high"],
      expected: "high",
    },
    {
      label: "returns null when nothing is available",
      desired: "high",
      available: [],
      expected: null,
    },
    {
      label:
        "falls back to the last available entry for an unranked desired level",
      desired: "last_used",
      available: ["low", "high", "max"],
      expected: "max",
    },
    {
      label: "picks the earlier entry on a ranking tie",
      desired: "high",
      available: ["medium", "xhigh"],
      expected: "medium",
    },
    {
      label:
        "clamps down to the nearest available level when ultracode is requested but unavailable",
      desired: "ultracode",
      available: ["low", "medium", "high", "xhigh", "max"],
      expected: "max",
    },
    {
      label: "returns ultracode directly when it is available",
      desired: "ultracode",
      available: ["high", "max", "ultracode"],
      expected: "ultracode",
    },
  ])("$label", ({ desired, available, expected }) => {
    expect(clampEffortToAvailable(desired, available)).toBe(expected);
  });

  it("includes ultracode in EFFORT_LEVELS so the ranking treats it as a real tier", () => {
    expect(EFFORT_LEVELS).toContain("ultracode");
  });
});

describe("deriveInitialConfig", () => {
  const restoreCases: Array<{
    label: string;
    option: SessionConfigOption;
    settingsOverride: Partial<PreviewSettingsSnapshot>;
    expectedCurrentValue: string;
  }> = [
    {
      label: "restores lastUsedContextWindow when the value is available",
      option: toggleOption("context_window", "1m", ["200k", "1m"]),
      settingsOverride: { lastUsedContextWindow: "200k" },
      expectedCurrentValue: "200k",
    },
    {
      label:
        "ignores lastUsedContextWindow when the value isn't in the option's values",
      option: toggleOption("context_window", "1m", ["1m"]),
      settingsOverride: { lastUsedContextWindow: "200k" },
      expectedCurrentValue: "1m",
    },
    {
      label: "restores lastUsedFastMode:true as 'on' when 'on' is available",
      option: toggleOption("fast", "off", ["on", "off"]),
      settingsOverride: { lastUsedFastMode: true },
      expectedCurrentValue: "on",
    },
    {
      label:
        "ignores lastUsedFastMode:true when 'on' isn't in the option's values",
      option: toggleOption("fast", "off", ["off"]),
      settingsOverride: { lastUsedFastMode: true },
      expectedCurrentValue: "off",
    },
  ];

  it.each(restoreCases)(
    "$label",
    ({ option, settingsOverride, expectedCurrentValue }) => {
      const result = deriveInitialConfig(
        [option],
        { ...baseSettings, ...settingsOverride },
        "claude",
      );

      const updated = result.find((o) => o.id === option.id);
      expect(updated).toMatchObject({ currentValue: expectedCurrentValue });
    },
  );
});

describe("applyConfigChange (toggle sync via context_window / fast)", () => {
  it("adds a toggle option that was previously absent, defaulting from settings", () => {
    const result = applyConfigChange([], {
      adapter: "claude",
      configId: "model",
      value: "claude-opus-5",
      effortOptions: undefined,
      contextWindowOptions: [{ value: "200k" }, { value: "1m" }],
      settings: { ...baseSettings, lastUsedContextWindow: "200k" },
    });

    expect(result.find((o) => o.id === "context_window")).toMatchObject({
      type: "select",
      category: "_context_window",
      currentValue: "200k",
      options: [{ value: "200k" }, { value: "1m" }],
    });
  });

  it("preserves the current value when it is still valid under the updated options", () => {
    const existing = toggleOption("context_window", "200k", ["200k", "1m"]);
    const result = applyConfigChange([existing], {
      adapter: "claude",
      configId: "model",
      value: "claude-opus-5",
      effortOptions: undefined,
      contextWindowOptions: [{ value: "200k" }, { value: "1m" }],
      settings: baseSettings,
    });

    expect(result.find((o) => o.id === "context_window")).toMatchObject({
      currentValue: "200k",
      options: [{ value: "200k" }, { value: "1m" }],
    });
  });

  it("falls back to the spec default when the current value is no longer among the options", () => {
    const existing = toggleOption("context_window", "500k", ["500k"]);
    const result = applyConfigChange([existing], {
      adapter: "claude",
      configId: "model",
      value: "claude-opus-5",
      effortOptions: undefined,
      contextWindowOptions: [{ value: "200k" }, { value: "1m" }],
      settings: baseSettings,
    });

    expect(result.find((o) => o.id === "context_window")).toMatchObject({
      currentValue: "1m",
    });
  });

  it("removes the toggle option when the model switch has no spec for it", () => {
    const existing = toggleOption("context_window", "1m", ["200k", "1m"]);
    const result = applyConfigChange([existing], {
      adapter: "codex",
      configId: "model",
      value: "gpt-5.6-sol",
      effortOptions: undefined,
      contextWindowOptions: undefined,
      settings: baseSettings,
    });

    expect(result.find((o) => o.id === "context_window")).toBeUndefined();
  });

  it("syncs the fast-mode toggle independently, defaulting to 'on' from lastUsedFastMode", () => {
    const result = applyConfigChange([], {
      adapter: "claude",
      configId: "model",
      value: "claude-opus-5",
      effortOptions: undefined,
      fastModeOptions: [{ value: "on" }, { value: "off" }],
      settings: { ...baseSettings, lastUsedFastMode: true },
    });

    expect(result.find((o) => o.id === "fast")).toMatchObject({
      currentValue: "on",
      category: "_fast_mode",
    });
  });

  it("leaves toggle options untouched for a non-model config change", () => {
    const existing = toggleOption("context_window", "1m", ["200k", "1m"]);
    const result = applyConfigChange([existing], {
      adapter: "claude",
      configId: "mode",
      value: "plan",
      effortOptions: undefined,
      settings: baseSettings,
    });

    expect(result.find((o) => o.id === "context_window")).toEqual(existing);
  });
});

describe("pickPreferredRunSelection", () => {
  const modelOption = {
    id: "model",
    name: "Model",
    type: "select",
    category: "model",
    currentValue: "claude-sonnet-5",
    description: "",
    options: [
      { value: "claude-sonnet-5", name: "claude-sonnet-5" },
      { value: "claude-opus-5", name: "claude-opus-5" },
    ],
  } as SessionConfigOption;

  it.each([
    {
      label: "takes the stored preference when nothing is picked locally",
      defaults: {
        runtime_adapter: "claude",
        model: "claude-opus-5",
        reasoning_effort: "high",
      },
      lastUsedModel: null,
      expected: { model: "claude-opus-5", reasoningEffort: "high" },
    },
    {
      label: "keeps an explicit local pick ahead of the preference",
      defaults: {
        runtime_adapter: "claude",
        model: "claude-opus-5",
        reasoning_effort: "high",
      },
      lastUsedModel: "claude-sonnet-5",
      expected: null,
    },
    {
      label: "ignores a preference stored for a different harness",
      defaults: {
        runtime_adapter: "codex",
        model: "gpt-5.5",
        reasoning_effort: "medium",
      },
      lastUsedModel: null,
      expected: null,
    },
    {
      label: "ignores a model this adapter no longer offers",
      defaults: {
        runtime_adapter: "claude",
        model: "claude-opus-4-8",
        reasoning_effort: "high",
      },
      lastUsedModel: null,
      expected: null,
    },
    {
      label: "drops an effort-less preference to the model's own default",
      defaults: {
        runtime_adapter: "claude",
        model: "claude-opus-5",
        reasoning_effort: null,
      },
      lastUsedModel: null,
      expected: { model: "claude-opus-5", reasoningEffort: null },
    },
    {
      label: "returns nothing when no preference is stored",
      defaults: {
        runtime_adapter: null,
        model: null,
        reasoning_effort: null,
      },
      lastUsedModel: null,
      expected: null,
    },
  ])("$label", ({ defaults, lastUsedModel, expected }) => {
    expect(
      pickPreferredRunSelection(defaults, "claude", modelOption, lastUsedModel),
    ).toEqual(expected);
  });
});
