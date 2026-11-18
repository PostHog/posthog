import { describe, expect, it } from "vitest";
import { isOfferedModel, isRetiredModel } from "./model-catalog";

describe("isOfferedModel", () => {
  it.each([
    "claude-opus-4-5",
    "claude-opus-4-6",
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "@cf/zai-org/glm-5.2",
    "claude-sonnet-4-5",
    "ANTHROPIC/CLAUDE-HAIKU-4-5",
    "gpt-5.2",
    "gpt-5.3",
    "gpt-5.3-codex",
    "OPENAI/GPT-5.3-CODEX",
    "gpt-5.4",
    "gpt-5-mini",
  ])("does not offer %s", (modelId) => {
    expect(isOfferedModel(modelId)).toBe(false);
  });

  it.each([
    "claude-opus-4-8",
    "claude-opus-5-5",
    "claude-sonnet-5",
    "anthropic/claude-opus-5-5",
    "zai-org/glm-5.3",
    "gpt-5.5",
    "gpt-6-sol",
    "OPENAI/GPT-6-SOL",
  ])("offers %s", (modelId) => {
    expect(isOfferedModel(modelId)).toBe(true);
  });
});

describe("isRetiredModel", () => {
  it.each(["claude-opus-4-7", "claude-sonnet-4-6", "@cf/zai-org/glm-5.2"])(
    "retires %s",
    (modelId) => {
      expect(isRetiredModel(modelId)).toBe(true);
    },
  );

  // A run may use an id the catalog never listed, so only a retired one is ruled out:
  // `gpt-5.5-codex` is a vendor variant a person's own OpenAI subscription drives.
  it.each(["gpt-5.5-codex", "claude-haiku-4-5", "claude-opus-5-5"])(
    "does not retire %s",
    (modelId) => {
      expect(isRetiredModel(modelId)).toBe(false);
    },
  );
});
