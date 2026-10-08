import { describe, expect, it } from "vitest";
import { heldPick, startingOptions } from "./starting";

describe("startingOptions", () => {
  it("offers pi's catalog on PostHog billing, starting on the harness default", () => {
    const options = startingOptions("posthog", "cloud", {});
    expect(options.model?.provider).toBe("posthog");
    expect(options.models.length).toBeGreaterThan(3);
    expect(options.models).toContainEqual(options.model);
    expect(options.effort).toBeNull();
    expect(options.efforts(options.models[0])).toContain("high");
  });

  it("offers Claude Code's models on an Anthropic plan, starting on the user's own settings", () => {
    const options = startingOptions("anthropic", "local", {
      model: "claude-fable-5-1",
      effortLevel: "high",
    });
    expect(options.model).toEqual({
      provider: "claude",
      id: "claude-fable-5-1",
      name: "Fable 5.1",
    });
    expect(options.effort).toBe("high");
    expect(
      options.models.every((model) => model.id.startsWith("claude-")),
    ).toBe(true);
    expect(
      startingOptions("anthropic", "local", { model: "nope" }).model?.id,
    ).not.toBe("nope");
  });

  it("offers Codex models on a ChatGPT plan, starting on GPT-5.5 locally", () => {
    const local = startingOptions("chatgpt", "local", {});
    expect(local.model?.id).toBe("gpt-5.5");
    expect(local.models.every((model) => model.id.startsWith("gpt-"))).toBe(
      true,
    );
    expect(startingOptions("chatgpt", "cloud", {}).model?.provider).toBe(
      "codex",
    );
  });

  it("drops a held pick the billing cannot start, keeping one it can", () => {
    const sol = { provider: "posthog", id: "gpt-6-sol", name: "Sol 6" };
    const anthropic = startingOptions("anthropic", "local", {});
    // The model goes, but the effort fits the plan's default model, so it stays.
    expect(heldPick({ model: sol, effort: "high" }, anthropic)).toEqual({
      effort: "high",
    });
    const opus = {
      provider: "claude",
      id: "claude-opus-5-5",
      name: "Opus 5.5",
    };
    expect(heldPick({ model: opus, effort: "high" }, anthropic)).toEqual({
      model: opus,
      effort: "high",
    });
    expect(heldPick({ effort: "high" }, anthropic)).toEqual({
      effort:
        anthropic.model && anthropic.efforts(anthropic.model).includes("high")
          ? "high"
          : undefined,
    });
  });
});
