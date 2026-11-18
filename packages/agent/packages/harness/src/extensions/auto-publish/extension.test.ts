import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { describe, expect, it } from "vitest";
import { createAutoPublishExtension } from "./extension";

describe("createAutoPublishExtension", () => {
  it("adds publishing instructions to Pi's system prompt", () => {
    const handlers = new Map<string, unknown>();
    const extension = createAutoPublishExtension();

    extension({
      on: (event: string, handler: unknown) => handlers.set(event, handler),
    } as unknown as ExtensionAPI);

    const beforeAgentStart = handlers.get("before_agent_start") as (event: {
      systemPrompt: string;
    }) => { systemPrompt: string };
    const result = beforeAgentStart({ systemPrompt: "Base system prompt" });

    expect(result.systemPrompt).toContain("Base system prompt");
    expect(result.systemPrompt).toContain("gh pr create --draft");
    expect(result.systemPrompt).toContain("git_signed_commit");
    // Pi never sees buildCloudSystemPrompt; this is its only stacking guidance.
    expect(result.systemPrompt).toContain("gh_stack");
    expect(result.systemPrompt).toContain("Default to a single pull request");
    expect(result.systemPrompt).toContain("Do not use the `gh stack` CLI");
  });
});
