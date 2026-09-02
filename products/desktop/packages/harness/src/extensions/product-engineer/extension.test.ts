import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { PRODUCT_ENGINEER_PROMPT } from "@posthog/shared/product-engineer-prompt";
import { describe, expect, it } from "vitest";
import { createProductEngineerExtension } from "./extension";

const UPSTREAM_SYSTEM_PROMPT = "Upstream pi instructions that may change.";

type BeforeAgentStart = (event: { systemPrompt: string }) => {
  systemPrompt: string;
};
type ResourcesDiscover = () => { skillPaths: string[] };

function setupExtension(): {
  beforeAgentStart: BeforeAgentStart;
  instrumentationSkillsDirectory: string;
  resourcesDiscover: ResourcesDiscover;
} {
  const handlers = new Map<string, unknown>();
  const instrumentationSkillsDirectory = fileURLToPath(
    new URL(".", import.meta.url),
  );

  createProductEngineerExtension(instrumentationSkillsDirectory)({
    on: (event: string, handler: unknown) => handlers.set(event, handler),
  } as unknown as ExtensionAPI);

  return {
    beforeAgentStart: handlers.get("before_agent_start") as BeforeAgentStart,
    instrumentationSkillsDirectory,
    resourcesDiscover: handlers.get("resources_discover") as ResourcesDiscover,
  };
}

describe("createProductEngineerExtension", () => {
  it("exposes bundled instrumentation skills through resource discovery", () => {
    const { instrumentationSkillsDirectory, resourcesDiscover } =
      setupExtension();

    expect(resourcesDiscover()).toEqual({
      skillPaths: [instrumentationSkillsDirectory],
    });
  });

  it("adds product engineering guidance without changing the upstream prompt", () => {
    const { beforeAgentStart } = setupExtension();

    expect(beforeAgentStart({ systemPrompt: UPSTREAM_SYSTEM_PROMPT })).toEqual({
      systemPrompt: `${PRODUCT_ENGINEER_PROMPT}\n\n${UPSTREAM_SYSTEM_PROMPT}`,
    });
  });

  it("does not add product engineering guidance twice", () => {
    const { beforeAgentStart } = setupExtension();
    const firstResult = beforeAgentStart({
      systemPrompt: UPSTREAM_SYSTEM_PROMPT,
    });

    expect(beforeAgentStart(firstResult)).toEqual(firstResult);
  });
});
