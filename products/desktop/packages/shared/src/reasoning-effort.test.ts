import { describe, expect, it } from "vitest";
import { isSupportedReasoningEffort } from "./reasoning-effort";

describe("isSupportedReasoningEffort", () => {
  it.each([
    ["codex", "gpt-5.5", "xhigh", true],
    ["codex", "gpt-5.6-sol", "max", true],
    ["codex", "gpt-5.4", "max", false],
    ["claude", "claude-opus-4-8", "xhigh", true],
    ["claude", "claude-sonnet-4-6", "xhigh", false],
    ["claude", "@cf/zai-org/glm-5.2", "high", true],
    ["claude", "@cf/zai-org/glm-5.2", "max", true],
    ["claude", "@cf/zai-org/glm-5.2", "medium", false],
    ["claude", "zai-org/glm-5.3", "high", true],
    ["claude", "zai-org/glm-5.3", "max", true],
    ["claude", "zai-org/glm-5.3", "medium", false],
    ["claude", "claude-opus-4-8", "minimal", false],
    ["claude", "claude-opus-5", "ultracode", true],
    ["claude", "claude-sonnet-5", "ultracode", true],
    ["claude", "claude-sonnet-4-6", "ultracode", false],
    ["codex", "gpt-5.6-sol", "ultracode", false],
  ] as const)(
    "validates %s %s effort %s",
    (adapter, modelId, effort, expected) => {
      expect(isSupportedReasoningEffort(adapter, modelId, effort)).toBe(
        expected,
      );
    },
  );
});
