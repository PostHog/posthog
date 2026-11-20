import { describe, expect, it } from "vitest";
import {
  prettifyScoutSkillName,
  scoutDisplayName,
  scoutNameForSkill,
  scoutNamesBySkill,
  withScoutNoun,
} from "./scout-names";

describe("prettifyScoutSkillName", () => {
  it.each([
    ["signals-scout-apm", "APM"],
    ["signals-scout-mcp-tool-calls", "MCP tool calls"],
    ["signals-scout-ai-observability", "AI observability"],
    ["signals-scout-csp-violations", "CSP violations"],
    ["signals-scout-llm-costs", "LLM costs"],
    ["signals-scout-pr-follow-up", "PR follow up"],
    ["signals-scout-error-tracking", "Error tracking"],
    ["custom_thing", "Custom thing"],
    ["weekly-seo-and-ux-review", "Weekly SEO and UX review"],
    ["posthog-github-sync", "PostHog GitHub sync"],
    ["signals-scout-constructor", "Constructor"],
  ])("names %s as %s", (skillName, expected) => {
    expect(prettifyScoutSkillName(skillName)).toBe(expected);
  });

  it("returns the input when nothing is left after the prefix", () => {
    expect(prettifyScoutSkillName("signals-scout-")).toBe("signals-scout-");
  });
});

describe("scoutDisplayName", () => {
  it("uses the team's display name verbatim", () => {
    expect(
      scoutDisplayName({
        skill_name: "signals-scout-apm",
        display_name: "Checkout latency (p95)",
      }),
    ).toBe("Checkout latency (p95)");
  });

  it.each([undefined, null, "", "   "])(
    "falls back to the skill name when the display name is %p",
    (display_name) => {
      expect(
        scoutDisplayName({ skill_name: "signals-scout-apm", display_name }),
      ).toBe("APM");
    },
  );
});

describe("scoutNameForSkill", () => {
  const names = scoutNamesBySkill([
    { skill_name: "signals-scout-apm", display_name: "Backend latency" },
    { skill_name: "signals-scout-mcp-tool-calls", display_name: "" },
  ]);

  it("resolves a configured scout to its display name", () => {
    expect(scoutNameForSkill(names, "signals-scout-apm")).toBe(
      "Backend latency",
    );
    expect(scoutNameForSkill(names, "signals-scout-mcp-tool-calls")).toBe(
      "MCP tool calls",
    );
  });

  it("prettifies a scout with no config", () => {
    expect(scoutNameForSkill(names, "signals-scout-csp-violations")).toBe(
      "CSP violations",
    );
    expect(scoutNameForSkill(undefined, "signals-scout-csp-violations")).toBe(
      "CSP violations",
    );
  });

  it.each([
    ["a scoutNamesBySkill map", names],
    ["a plain object map", { "signals-scout-apm": "Backend latency" }],
  ])("does not resolve skill names to inherited keys of %s", (_label, map) => {
    expect(scoutNameForSkill(map, "constructor")).toBe("Constructor");
    expect(scoutNameForSkill(map, "toString")).toBe("Tostring");
  });

  it("builds a map that callers can index without hitting inherited keys", () => {
    expect(names.constructor).toBeUndefined();
  });
});

describe("withScoutNoun", () => {
  it.each([
    ["APM", "APM scout"],
    ["Checkout scout", "Checkout scout"],
    ["Scouting report", "Scouting report scout"],
  ])("names %s as %s", (name, expected) => {
    expect(withScoutNoun(name)).toBe(expected);
  });
});
