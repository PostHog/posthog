import { describe, expect, it } from "vitest";
import { IMAGE_PRESET_TOOLS, imagePresetBrief } from "./imagePreset";

describe("imagePresetBrief", () => {
  it("carries each pinned version, so the builder installs the vetted release", () => {
    const brief = imagePresetBrief("PostHog/posthog", IMAGE_PRESET_TOOLS, []);
    const pinned = IMAGE_PRESET_TOOLS.filter((tool) => tool.version);
    expect(pinned.length).toBeGreaterThan(0);
    for (const tool of pinned) {
      expect(brief).toContain(`${tool.command}@${tool.version}`);
    }
  });

  it("leaves unpinned tools without a version marker", () => {
    const brief = imagePresetBrief("PostHog/posthog", IMAGE_PRESET_TOOLS, []);
    expect(brief).not.toContain("@undefined");
    const unpinned = IMAGE_PRESET_TOOLS.filter((tool) => !tool.version);
    expect(unpinned.length).toBeGreaterThan(0);
    for (const tool of unpinned) {
      expect(brief).toContain(`- ${tool.command} (${tool.name}):`);
    }
  });
});
