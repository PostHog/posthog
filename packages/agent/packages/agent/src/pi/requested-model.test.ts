import { describe, expect, it } from "vitest";
import { resolveRequestedModel } from "./requested-model";

describe("resolveRequestedModel", () => {
  const known: Record<string, string[]> = {
    posthog: ["claude-opus-5-5", "moonshotai/kimi-k3"],
    "openai-codex": ["gpt-5.5"],
  };
  const getModel = (provider: string, id: string) =>
    known[provider]?.includes(id) ? { provider, id } : undefined;

  it.each([
    ["posthog/claude-opus-5-5", { provider: "posthog", id: "claude-opus-5-5" }],
    ["claude-opus-5-5", { provider: "posthog", id: "claude-opus-5-5" }],
    ["moonshotai/kimi-k3", { provider: "posthog", id: "moonshotai/kimi-k3" }],
    ["openai-codex/gpt-5.5", { provider: "openai-codex", id: "gpt-5.5" }],
  ])("finds %s", (requested, model) => {
    expect(resolveRequestedModel(getModel, requested)).toEqual(model);
  });

  it("throws for a model no provider has", () => {
    expect(() => resolveRequestedModel(getModel, "openai-codex/gpt-9")).toThrow(
      "Model not found: openai-codex/gpt-9",
    );
  });
});
