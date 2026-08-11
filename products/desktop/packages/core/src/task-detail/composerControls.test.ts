import {
  type CloudTaskConfigOption,
  DEFAULT_GATEWAY_MODEL,
  restrictedModelMeta,
} from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  getComposerModelOptions,
  resolveComposerPrimaryAction,
} from "./composerControls";

describe("getComposerModelOptions", () => {
  it("adapts live model options for the picker, disabling restricted ones", () => {
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
});

describe("resolveComposerPrimaryAction", () => {
  it.each([
    [{ hasContent: true }, "send"],
    [{ canStop: true }, "stop"],
    [{ canStop: true, hasContent: true }, "send"],
    [{ canStop: true, hasContent: true, allowSendWhileRunning: false }, "stop"],
    [{ isRecording: true }, "mic-stop"],
    [{}, "mic"],
    [{ disabled: true, hasContent: true }, "disabled"],
    [{ isTranscribing: true }, "disabled"],
  ])("derives %s", (overrides, expected) => {
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
