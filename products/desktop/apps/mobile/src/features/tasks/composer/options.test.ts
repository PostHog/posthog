import {
  type CloudTaskConfigOption,
  DEFAULT_GATEWAY_MODEL,
  restrictedModelMeta,
} from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  filterKimiModelConfigOptions,
  filterKimiModelOption,
  getAgentPresets,
  getComposerModelOptions,
  getMiddlePreset,
  getMobileExecutionModes,
  resolveComposerPrimaryAction,
  resolveHarnessSwitchSelection,
} from "./options";

const KIMI = "moonshotai/kimi-k3";

const kimiModelOption: CloudTaskConfigOption = {
  id: "model",
  name: "Model",
  type: "select",
  currentValue: DEFAULT_GATEWAY_MODEL,
  options: [
    { value: DEFAULT_GATEWAY_MODEL, name: "Claude Opus 4.8" },
    { value: KIMI, name: "Kimi K3" },
  ],
  category: "model",
  description: "Choose a model",
};

const modelOption: CloudTaskConfigOption = {
  id: "model",
  name: "Model",
  type: "select",
  currentValue: DEFAULT_GATEWAY_MODEL,
  options: [
    { value: DEFAULT_GATEWAY_MODEL, name: "Claude Opus 4.8" },
    {
      value: "claude-fable-5",
      name: "Claude Fable 5",
      _meta: restrictedModelMeta(),
    },
  ],
  category: "model",
  description: "Choose a model",
};

describe("mobile composer options", () => {
  it("hides unrestricted execution modes", () => {
    expect(
      getMobileExecutionModes([
        { id: "plan", name: "Plan", description: "Plan first" },
        {
          id: "bypassPermissions",
          name: "Bypass permissions",
          description: "Allow everything",
        },
        {
          id: "full-access",
          name: "Full access",
          description: "Allow everything",
        },
      ]).map((mode) => mode.id),
    ).toEqual(["plan"]);
  });

  it("adapts live model options for the mobile picker", () => {
    expect(getComposerModelOptions(modelOption)).toEqual([
      {
        value: DEFAULT_GATEWAY_MODEL,
        label: "Claude Opus 4.8",
        description: undefined,
        disabled: false,
      },
      {
        value: "claude-fable-5",
        label: "Claude Fable 5",
        description: undefined,
        disabled: true,
      },
    ]);
  });

  describe("filterKimiModelOption", () => {
    it("keeps Kimi K3 when the flag is on", () => {
      const filtered = filterKimiModelOption(kimiModelOption, true);
      expect(filtered.options.map((o) => o.value)).toContain(KIMI);
    });

    it("drops Kimi K3 when the flag is off", () => {
      const filtered = filterKimiModelOption(kimiModelOption, false);
      expect(filtered.options.map((o) => o.value)).not.toContain(KIMI);
      expect(filtered.options.map((o) => o.value)).toEqual([
        DEFAULT_GATEWAY_MODEL,
      ]);
    });

    it("rewrites a persisted Kimi selection to a visible model when the flag is off", () => {
      const filtered = filterKimiModelOption(
        { ...kimiModelOption, currentValue: KIMI },
        false,
      );
      expect(filtered.currentValue).toBe(DEFAULT_GATEWAY_MODEL);
    });

    it("leaves an already-visible selection untouched when the flag is off", () => {
      const filtered = filterKimiModelOption(kimiModelOption, false);
      expect(filtered.currentValue).toBe(DEFAULT_GATEWAY_MODEL);
    });
  });

  describe("filterKimiModelConfigOptions", () => {
    const modeOption: CloudTaskConfigOption = {
      id: "mode",
      name: "Mode",
      type: "select",
      currentValue: "plan",
      options: [{ value: "plan", name: "Plan" }],
      category: "mode",
      description: "Execution mode",
    };

    it("returns the config set untouched when the flag is on", () => {
      const input = [modeOption, kimiModelOption];
      expect(filterKimiModelConfigOptions(input, true)).toBe(input);
    });

    it("strips Kimi from only the model option when the flag is off", () => {
      const filtered = filterKimiModelConfigOptions(
        [modeOption, kimiModelOption],
        false,
      );
      const model = filtered.find((option) => option.category === "model");
      const mode = filtered.find((option) => option.category === "mode");
      expect(model?.options.map((o) => o.value)).toEqual([
        DEFAULT_GATEWAY_MODEL,
      ]);
      expect(mode).toBe(modeOption);
    });
  });

  describe("agent presets", () => {
    const ladderConfig: CloudTaskConfigOption = {
      id: "model",
      name: "Model",
      type: "select",
      currentValue: "claude-opus-5",
      options: [
        { value: "claude-sonnet-5", name: "Claude Sonnet 5" },
        { value: "claude-opus-5", name: "Claude Opus 5" },
        // Restricted models drop out of the scale entirely.
        {
          value: "claude-fable-5",
          name: "Claude Fable 5",
          _meta: restrictedModelMeta(),
        },
      ],
      category: "model",
      description: "Choose a model",
    };

    it("maps only the offered, unrestricted, effort-valid ladder notches", () => {
      expect(getAgentPresets("claude", ladderConfig)).toEqual([
        {
          model: "claude-sonnet-5",
          effort: "medium",
          modelLabel: "Claude Sonnet 5",
          effortLabel: "Medium",
        },
        {
          model: "claude-sonnet-5",
          effort: "high",
          modelLabel: "Claude Sonnet 5",
          effortLabel: "High",
        },
        {
          model: "claude-opus-5",
          effort: "medium",
          modelLabel: "Claude Opus 5",
          effortLabel: "Medium",
        },
        {
          model: "claude-opus-5",
          effort: "xhigh",
          modelLabel: "Claude Opus 5",
          effortLabel: "Extra High",
        },
      ]);
    });

    it("returns the balanced middle notch", () => {
      const presets = getAgentPresets("claude", ladderConfig);
      expect(getMiddlePreset(presets)).toEqual({
        model: "claude-sonnet-5",
        effort: "high",
        modelLabel: "Claude Sonnet 5",
        effortLabel: "High",
      });
      expect(getMiddlePreset([])).toBeUndefined();
    });
  });

  describe("resolveHarnessSwitchSelection", () => {
    it("switches to the codex middle notch", () => {
      expect(resolveHarnessSwitchSelection("claude")).toMatchObject({
        adapter: "codex",
        model: "gpt-5.6-sol",
        reasoning: "medium",
      });
    });

    it("switches to the claude middle notch", () => {
      expect(resolveHarnessSwitchSelection("codex")).toMatchObject({
        adapter: "claude",
        model: "claude-opus-5",
        reasoning: "medium",
      });
    });
  });

  it.each([
    [{ hasContent: true }, "send"],
    [{ canStop: true }, "stop"],
    [{ isRecording: true }, "mic-stop"],
    [{ isRecording: true, canStop: true }, "mic-stop"],
    [{}, "mic"],
  ])("derives the mobile primary action", (overrides, expected) => {
    expect(
      resolveComposerPrimaryAction({
        hasContent: false,
        disabled: false,
        isRecording: false,
        isTranscribing: false,
        canStop: false,
        allowSendWhileRunning: true,
        ...overrides,
      }),
    ).toBe(expected);
  });
});
