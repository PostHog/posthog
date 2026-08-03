import { describe, expect, it } from "vitest";
import { extractAlwaysOnSkills, hasAlwaysOnSkills } from "./alwaysOnSkills";

const PREAMBLE =
  "The user has marked these skills as always-on: their instructions apply to this entire session, from your first response on, without being explicitly invoked. If a skill conflicts with the user's message, the message wins.";

describe("extractAlwaysOnSkills", () => {
  it("returns null when there is no always-on-skills element", () => {
    expect(extractAlwaysOnSkills("just a normal prompt")).toBeNull();
    expect(hasAlwaysOnSkills("just a normal prompt")).toBe(false);
  });

  it("extracts referenced skill names and strips the element (cloud form)", () => {
    const content = `Ship the fix\n\n<always_on_skills>\n${PREAMBLE}\n\n- /i-have-adhd: Focus aid\n- /max (preinstalled PostHog skill)\n</always_on_skills>`;
    const result = extractAlwaysOnSkills(content);
    expect(result?.stripped).toBe("Ship the fix");
    expect(result?.mention.names).toEqual(["i-have-adhd", "max"]);
    expect(result?.mention.body).toContain("- /i-have-adhd: Focus aid");
    expect(hasAlwaysOnSkills(content)).toBe(true);
  });

  it("extracts inlined skill names (local form)", () => {
    const content = `Ship the fix\n\n<always_on_skills>\n${PREAMBLE}\n\n--- BEGIN ALWAYS-ON SKILL i-have-adhd ---\nStay focused.\n--- END ALWAYS-ON SKILL i-have-adhd ---\nSkill directory: /skills/i-have-adhd\n</always_on_skills>`;
    const result = extractAlwaysOnSkills(content);
    expect(result?.stripped).toBe("Ship the fix");
    expect(result?.mention.names).toEqual(["i-have-adhd"]);
  });

  it("preserves user-authored always-on-skills tags", () => {
    const content =
      "Render this example: <always_on_skills>- /fake</always_on_skills>";
    expect(extractAlwaysOnSkills(content)).toBeNull();
    expect(hasAlwaysOnSkills(content)).toBe(false);
  });
});
