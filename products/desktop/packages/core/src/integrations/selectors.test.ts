import { describe, expect, it } from "vitest";
import { classifyIntegrations, type Integration } from "./selectors";

const integration = (id: number, kind: string): Integration => ({ id, kind });

describe("classifyIntegrations", () => {
  it("splits integrations by provider kind and derives presence flags", () => {
    const result = classifyIntegrations([
      integration(1, "github"),
      integration(2, "slack"),
      integration(3, "github"),
      integration(4, "other"),
    ]);

    expect(result.githubIntegrations.map((i) => i.id)).toEqual([1, 3]);
    expect(result.slackIntegrations.map((i) => i.id)).toEqual([2]);
    expect(result.hasGithubIntegration).toBe(true);
    expect(result.hasSlackIntegration).toBe(true);
  });

  it("reports no integrations for an empty list", () => {
    const result = classifyIntegrations([]);
    expect(result.hasGithubIntegration).toBe(false);
    expect(result.hasSlackIntegration).toBe(false);
  });
});
