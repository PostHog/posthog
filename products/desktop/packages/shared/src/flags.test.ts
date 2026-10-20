import { BEDROCK_LLM_GATEWAY_FLAG } from "@posthog/agent-contracts/bedrock-gateway";
import { describe, expect, it } from "vitest";
import featureFlagKeys from "./feature-flag-keys.json" with { type: "json" };
import { MODEL_ACCESS_FLAGS } from "./model-catalog";

describe("flags", () => {
  it("keeps the Bedrock gateway flag literal in step with the flag registry", () => {
    expect(BEDROCK_LLM_GATEWAY_FLAG).toBe(
      featureFlagKeys.BEDROCK_LLM_GATEWAY_FLAG,
    );
  });

  it("lists every model rollout flag in the flag registry", () => {
    const registered = new Set<string>(Object.values(featureFlagKeys));
    expect(MODEL_ACCESS_FLAGS.filter((flag) => !registered.has(flag))).toEqual(
      [],
    );
  });
});
