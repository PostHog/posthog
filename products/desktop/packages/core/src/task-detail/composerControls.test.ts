import { describe, expect, it } from "vitest";
import { resolveComposerPrimaryAction } from "./composerControls";

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
