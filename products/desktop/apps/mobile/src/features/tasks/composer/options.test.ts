import {
  type CloudTaskConfigOption,
  type CloudTaskConfigSelectGroup,
  restrictedModelMeta,
} from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  getAgentPresets,
  getMiddlePreset,
  getMobileExecutionModes,
  harnessForModel,
  resolveComposerPrimaryAction,
  resolveCrossHarnessModelSelection,
  toMobileModelGroups,
} from "./options";

const HARNESS_META = "posthog.code/modelHarness";

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

  describe("agent presets", () => {
    const ladderConfig: CloudTaskConfigOption = {
      id: "model",
      name: "Model",
      type: "select",
      currentValue: "claude-opus-5",
      options: [
        { value: "claude-sonnet-5", name: "Claude Sonnet 5" },
        { value: "claude-opus-5", name: "Claude Opus 5" },
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

  describe("harnessForModel", () => {
    const groups: CloudTaskConfigSelectGroup[] = [
      {
        group: "anthropic",
        name: "Anthropic",
        options: [
          {
            value: "claude-opus-5",
            name: "Claude Opus 5",
            _meta: { [HARNESS_META]: "claude" },
          },
        ],
      },
      {
        group: "openai",
        name: "OpenAI",
        options: [
          {
            value: "gpt-5.6-sol",
            name: "GPT-5.6 Sol",
            _meta: { [HARNESS_META]: "codex" },
          },
        ],
      },
    ];

    it("reads the harness stamp from the picked option", () => {
      expect(harnessForModel(groups, "gpt-5.6-sol")).toBe("codex");
    });

    it("falls back to the model id shape when the pick is not in the catalog", () => {
      // A gateway blip may have dropped the model; the composer must still let
      // the currently-running model stay picked, so the harness has to resolve.
      expect(harnessForModel(groups, "gpt-5.9-nova")).toBe("codex");
      expect(harnessForModel(groups, "claude-opus-4-99")).toBe("claude");
    });
  });

  describe("resolveCrossHarnessModelSelection", () => {
    it("lands on the target harness's default mode and reasoning", () => {
      expect(resolveCrossHarnessModelSelection("codex", "gpt-5.6-sol")).toEqual(
        {
          adapter: "codex",
          mode: "auto",
          model: "gpt-5.6-sol",
          reasoning: "high",
        },
      );
    });
  });

  it("keys mobile groups on their vendor and adapts each option", () => {
    const groups: CloudTaskConfigSelectGroup[] = [
      {
        group: "anthropic",
        name: "Anthropic",
        options: [
          {
            value: "claude-opus-5",
            name: "Claude Opus 5",
            _meta: restrictedModelMeta(),
          },
        ],
      },
    ];
    expect(toMobileModelGroups(groups)).toEqual([
      {
        key: "anthropic",
        name: "Anthropic",
        options: [
          {
            value: "claude-opus-5",
            label: "Claude Opus 5",
            description: undefined,
            disabled: true,
          },
        ],
      },
    ]);
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
