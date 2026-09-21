import { describe, expect, it } from "vitest";
import { BEDROCK_LLM_GATEWAY_FLAG } from "./bedrock-gateway";
import featureFlagKeys from "./feature-flag-keys.json" with { type: "json" };

describe("flags", () => {
  it("keeps the Bedrock gateway flag literal in step with the flag registry", () => {
    expect(BEDROCK_LLM_GATEWAY_FLAG).toBe(
      featureFlagKeys.BEDROCK_LLM_GATEWAY_FLAG,
    );
  });
});
