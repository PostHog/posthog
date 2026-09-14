import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { SIMPLIFIED_TECHNICAL_ENGLISH_INSTRUCTION } from "@posthog/shared/product-engineer-prompt";
import { afterEach, describe, expect, it, vi } from "vitest";
import { harnessExtensionFiles, harnessExtensions } from "./registry";

describe("harness extensions", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("loads Benjamin guidance for Pi runtimes", () => {
    vi.stubEnv("POSTHOG_BENJAMIN", "1");
    const extension = harnessExtensions().find(
      ({ name }) => name === "benjamin-guidance",
    );
    if (!extension || typeof extension === "function") {
      throw new Error("Benjamin guidance extension is not registered");
    }

    const handlers = new Map<string, unknown>();
    extension.factory({
      on: (event: string, handler: unknown) => handlers.set(event, handler),
    } as unknown as ExtensionAPI);
    const beforeAgentStart = handlers.get("before_agent_start") as (event: {
      systemPrompt: string;
    }) => { systemPrompt: string };

    const systemPrompt = beforeAgentStart({
      systemPrompt: "Pi instructions",
    }).systemPrompt;

    expect(systemPrompt).toContain("BENJAMIN-PLUS MODE ACTIVE");
    expect(systemPrompt).toContain(SIMPLIFIED_TECHNICAL_ENGLISH_INSTRUCTION);
    expect(
      harnessExtensionFiles().some((file) =>
        file.endsWith("benjamin-guidance/index.js"),
      ),
    ).toBe(true);
  });
});
