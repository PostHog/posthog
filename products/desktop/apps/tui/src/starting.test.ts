import { describe, expect, it } from "vitest";
import { startingOptions } from "./starting";

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
});
