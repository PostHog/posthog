import { describe, expect, it } from "vitest";
import { buildContextGenerationPrompt } from "./contextPrompt";

const input = {
  channelName: "activation-research",
  channelId: "11111111-2222-4333-8444-555555555555",
  description: "Document the activation workflow.",
};

describe("buildContextGenerationPrompt", () => {
  it("publishes through the context wiki when the context layer is enabled", () => {
    const prompt = buildContextGenerationPrompt({
      ...input,
      contextLayerEnabled: true,
    });

    expect(prompt).toContain("context-wiki-channel-resolve");
    expect(prompt).toContain("context-wiki-page-retrieve");
    expect(prompt).toContain("context-wiki-page-update");
    expect(prompt).toContain(`channel_id: ${input.channelId}`);
    expect(prompt).not.toContain("channel-instructions-update");
    expect(prompt).toContain("Do not call any `loop-*` context tool");
  });

  it("keeps the legacy publishing path when the context layer is disabled", () => {
    const prompt = buildContextGenerationPrompt(input);

    expect(prompt).toContain("channel-instructions-update");
    expect(prompt).not.toContain("context-wiki-page-update");
  });
});
