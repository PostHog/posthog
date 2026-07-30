import type { CloudRegion } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { agentIngressBaseUrl } from "./ingress";

describe("agentIngressBaseUrl", () => {
  it.each<{ region: CloudRegion; expected: string }>([
    { region: "us", expected: "https://my-agent.agents.us.posthog.com" },
    { region: "eu", expected: "https://my-agent.agents.eu.posthog.com" },
    { region: "dev", expected: "http://localhost:3030/agents/my-agent" },
  ])("builds the $region URL for a valid slug", ({ region, expected }) => {
    expect(agentIngressBaseUrl("my-agent", region)).toBe(expected);
  });

  it.each(["evil.com/", ""])("refuses to interpolate the slug %s", (slug) => {
    expect(agentIngressBaseUrl(slug, "us")).toBeNull();
  });

  it("returns null without a region", () => {
    expect(agentIngressBaseUrl("my-agent", null)).toBeNull();
  });
});
