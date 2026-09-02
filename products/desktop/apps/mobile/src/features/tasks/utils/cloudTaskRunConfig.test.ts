import { describe, expect, it } from "vitest";
import { buildCloudTaskRunConfig } from "./cloudTaskRunConfig";

describe("buildCloudTaskRunConfig", () => {
  it("forwards the selected Codex configuration to cloud task dispatch", () => {
    expect(
      buildCloudTaskRunConfig({
        adapter: "codex",
        mode: "full-access",
        model: "gpt-5.5",
        reasoning: "high",
      }),
    ).toEqual({
      adapter: "codex",
      initialPermissionMode: "full-access",
      model: "gpt-5.5",
      reasoningLevel: "high",
    });
  });

  it("omits reasoning when the selected model does not support it", () => {
    expect(
      buildCloudTaskRunConfig({
        adapter: "claude",
        mode: "plan",
        model: "claude-haiku-4-5",
        reasoning: "high",
      }).reasoningLevel,
    ).toBeUndefined();
  });

  it("sends context window and fast mode for a supporting model", () => {
    expect(
      buildCloudTaskRunConfig({
        adapter: "claude",
        mode: "plan",
        model: "claude-opus-4-8",
        reasoning: "high",
        contextWindow: "200k",
        fastMode: true,
      }),
    ).toEqual({
      adapter: "claude",
      model: "claude-opus-4-8",
      reasoningLevel: "high",
      initialPermissionMode: "plan",
      contextWindow: "200k",
      fastMode: true,
    });
  });

  it("omits fast mode for a model that supports 1M context but not fast mode", () => {
    const config = buildCloudTaskRunConfig({
      adapter: "claude",
      mode: "plan",
      model: "claude-sonnet-5",
      reasoning: "high",
      contextWindow: "1m",
      fastMode: true,
    });
    expect(config).toMatchObject({ contextWindow: "1m" });
    expect(config).not.toHaveProperty("fastMode");
  });

  it("omits context window for a model without the 1M beta", () => {
    const config = buildCloudTaskRunConfig({
      adapter: "claude",
      mode: "plan",
      model: "claude-haiku-4-5",
      reasoning: "high",
      contextWindow: "1m",
      fastMode: true,
    });
    expect(config).not.toHaveProperty("contextWindow");
    expect(config).not.toHaveProperty("fastMode");
  });
});
