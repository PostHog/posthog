import { describe, expect, it } from "vitest";
import {
  applyAvailableModelsAllowlist,
  resolveInitialModelId,
} from "./model-config";

const rawModelOptions = {
  currentModelId: "claude-opus-4-8",
  options: [
    { value: "claude-opus-4-8", name: "Claude Opus 4.8" },
    { value: "claude-sonnet-4-6", name: "Claude Sonnet 4.6" },
  ],
};

describe("applyAvailableModelsAllowlist", () => {
  it("falls back to the unfiltered gateway list when every allowlisted model is unknown", () => {
    expect(
      applyAvailableModelsAllowlist(rawModelOptions, ["claude-unknown-model"]),
    ).toEqual(rawModelOptions);
  });

  it("reorders the allowlist to the picker order instead of the listed order", () => {
    expect(
      applyAvailableModelsAllowlist(rawModelOptions, [
        "claude-sonnet-4-6",
        "claude-opus-4-8",
      ]).options,
    ).toEqual([
      { value: "claude-opus-4-8", name: "Claude Opus 4.8" },
      { value: "claude-sonnet-4-6", name: "Claude Sonnet 4.6" },
    ]);
  });

  it("switches the current model when the previous one is filtered out", () => {
    expect(
      applyAvailableModelsAllowlist(rawModelOptions, ["claude-sonnet-4-6"]),
    ).toEqual({
      currentModelId: "claude-sonnet-4-6",
      options: [{ value: "claude-sonnet-4-6", name: "Claude Sonnet 4.6" }],
    });
  });
});

describe("resolveInitialModelId", () => {
  it("keeps a preferred model when it survives filtering", () => {
    const filteredModelOptions = applyAvailableModelsAllowlist(
      rawModelOptions,
      ["claude-opus-4-8", "claude-sonnet-4-6"],
    );

    expect(
      resolveInitialModelId(filteredModelOptions, [
        "claude-opus-4-8",
        "claude-sonnet-4-6",
      ]),
    ).toBe("claude-opus-4-8");
  });

  it("falls back to the filtered current model when the preferred one is disallowed", () => {
    const filteredModelOptions = applyAvailableModelsAllowlist(
      rawModelOptions,
      ["claude-sonnet-4-6"],
    );

    expect(
      resolveInitialModelId(filteredModelOptions, [
        "claude-opus-4-8",
        "claude-sonnet-4-6",
      ]),
    ).toBe("claude-sonnet-4-6");
  });
});
