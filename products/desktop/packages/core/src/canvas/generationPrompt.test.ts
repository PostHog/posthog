import { describe, expect, it } from "vitest";
import { buildCanvasGenerationPrompt } from "./generationPrompt";

describe("buildCanvasGenerationPrompt", () => {
  const base = {
    dashboardId: "dash-1",
    name: "Signups",
    channelName: "growth",
    instruction: "add a retention chart",
    isEdit: false,
  };

  it("leads with the user's instruction and wraps the routing in the collapsible tag", () => {
    const prompt = buildCanvasGenerationPrompt(base);
    // The visible message is the bare instruction; the boilerplate lives in the
    // tag the conversation UI collapses (extractCanvasInstructions).
    expect(prompt.startsWith("add a retention chart\n\n")).toBe(true);
    expect(prompt).toContain("<canvas_generation_instructions>");
    expect(prompt).toContain("</canvas_generation_instructions>");
  });

  it("routes into the bundled canvas skills with the target canvas preselected", () => {
    const prompt = buildCanvasGenerationPrompt(base);
    expect(prompt).toContain("`building-canvases` skill");
    expect(prompt).toContain('canvas id: "dash-1"');
    // Guarded publish loop via the typed canvas tools — not a local file, not a
    // code reply, and never an unguarded overwrite.
    expect(prompt).toContain("desktop-file-system-canvas-source-retrieve");
    expect(prompt).toContain("desktop-file-system-canvas-publish-create");
    expect(prompt).toContain("expected_current_version_id");
    // The authoring contract itself lives in the skills, not the prompt.
    expect(prompt).not.toContain("OUTPUT FORMAT");
    expect(prompt).not.toContain("IMPORTS");
  });

  it.each([
    [false, "Build the canvas"],
    [true, "Edit the canvas"],
  ])("isEdit=%s picks the right header", (isEdit, header) => {
    expect(buildCanvasGenerationPrompt({ ...base, isEdit })).toContain(header);
  });

  it.each([
    ["first build with starter", false, true, true],
    ["first build without starter", false, false, false],
    ["edit ignores starter", true, true, false],
  ])("%s", (_name, isEdit, useStarter, expectStarter) => {
    const prompt = buildCanvasGenerationPrompt({ ...base, isEdit, useStarter });
    expect(prompt.includes("starter scaffold")).toBe(expectStarter);
  });

  it("adds a layout hint for legacy template ids only", () => {
    expect(
      buildCanvasGenerationPrompt({ ...base, templateId: "web-analytics" }),
    ).toContain("web analytics board");
    expect(buildCanvasGenerationPrompt(base)).not.toContain("Template:");
  });
});
