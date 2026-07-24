import { describe, expect, it } from "vitest";
import { fallbackModelConfigs } from "../posthog-provider/models";
import {
  findBundledAgent,
  listBundledAgentNames,
  loadBundledAgents,
} from "./agents";

describe("agents", () => {
  it("ships exactly the three expected bundled agents", () => {
    expect(listBundledAgentNames()).toEqual(["Explore", "General", "Plan"]);
  });

  it.each(
    loadBundledAgents()
      .filter((agent) => agent.name !== "General")
      .map((agent) => [agent.name, agent] as const),
  )("%s has a non-empty description and system prompt", (_name, agent) => {
    expect(agent.description.length).toBeGreaterThan(0);
    expect(agent.systemPrompt.trim().length).toBeGreaterThan(0);
    expect(agent.source).toBe("bundled");
  });

  it("General has a non-empty description but a deliberately empty system prompt", () => {
    // Unlike Explore/Plan, General has no custom persona text at all: an
    // empty body means run-agent.ts never passes `--system-prompt`, so the
    // child falls through to computing pi's own live default system prompt
    // (tools list, guidelines merged from every loaded extension, project
    // context, skills) instead of a narrower hand-written one that would
    // drift out of sync with pi's real template over time.
    const general = findBundledAgent("General");
    expect(general?.description.length).toBeGreaterThan(0);
    expect(general?.systemPrompt.trim()).toBe("");
    expect(general?.source).toBe("bundled");
  });

  it("Explore is read-only and pinned to a fast model", () => {
    const explore = findBundledAgent("Explore");
    expect(explore?.tools).toEqual(["read", "bash", "grep", "find", "ls"]);
    expect(explore?.model).toBe("claude-haiku-4-5");
  });

  it("Plan is read-only and inherits the parent's model", () => {
    const plan = findBundledAgent("Plan");
    expect(plan?.tools).toEqual(["read", "bash", "grep", "find", "ls"]);
    expect(plan?.model).toBeUndefined();
  });

  it("General is the only bundled agent with write access, and inherits the parent's model", () => {
    const general = findBundledAgent("General");
    expect(general?.tools).toEqual([
      "read",
      "bash",
      "edit",
      "write",
      "grep",
      "find",
      "ls",
    ]);
    expect(general?.model).toBeUndefined();
    for (const agent of loadBundledAgents()) {
      if (agent.name === "General") continue;
      expect(agent.tools).not.toContain("edit");
      expect(agent.tools).not.toContain("write");
    }
  });

  it("findBundledAgent resolves a known agent and returns undefined for an unknown one", () => {
    expect(findBundledAgent("Explore")?.name).toBe("Explore");
    expect(findBundledAgent("does-not-exist")).toBeUndefined();
  });

  // Regression test for a real bug: `bundled-agents/Explore.md` once pinned
  // `model: anthropic/claude-haiku-4-5`. This provider registers every
  // vendor's models (Anthropic, OpenAI, Cloudflare) under one gateway
  // provider name (`posthog`) with bare ids like `claude-haiku-4-5` — there
  // is no provider literally named `anthropic` in `ctx.modelRegistry`. A
  // `vendor/id`-shaped pin therefore never resolves in `auth.ts` and
  // silently falls through to inheriting the parent's current model — no
  // error, no warning, just a "fast" agent quietly running on whatever
  // (possibly large, slow) model the parent session happened to be on.
  // `auth.test.ts`'s fakes can't catch this: they invent their own
  // provider/model names, so they never notice a mismatch against this
  // repo's real provider shape. This test closes that gap by resolving
  // every bundled agent's pinned `model` against the real (offline-safe)
  // model list this provider actually registers.
  it("every bundled agent's pinned model exists in the real provider's model list, unprefixed", () => {
    const realModelIds = fallbackModelConfigs("us").map((m) => m.id);

    for (const agent of loadBundledAgents()) {
      if (!agent.model) continue; // unset is valid — it means "inherit"

      expect(
        agent.model.includes("/"),
        `${agent.name}'s model ("${agent.model}") looks provider-prefixed, but this provider registers every vendor's models under one bare-id namespace — use the bare id instead`,
      ).toBe(false);

      expect(
        realModelIds,
        `${agent.name}'s pinned model ("${agent.model}") doesn't exist in the real provider's model list, so it will silently fall back to inheriting the parent's model instead of actually running on the pinned model`,
      ).toContain(agent.model);
    }
  });
});
