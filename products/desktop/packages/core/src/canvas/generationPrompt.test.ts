import { describe, expect, it } from "vitest";
import { FREEFORM_TEMPLATE_ID } from "./freeformSchemas";
import { buildCanvasGenerationPrompt } from "./generationPrompt";

describe("buildCanvasGenerationPrompt", () => {
  const base = {
    dashboardId: "dash-1",
    name: "Signups",
    channelName: "growth",
    instruction: "add a retention chart",
  };

  it("leads with the request and routes the target through the canvas skill", () => {
    const prompt = buildCanvasGenerationPrompt(base);
    expect(prompt.startsWith("add a retention chart\n\n")).toBe(true);
    expect(prompt).toContain("<canvas_generation_instructions>");
    expect(prompt).toContain("`building-canvases` skill");
    expect(prompt).toContain('canvas id: "dash-1"');
    expect(prompt).not.toContain("canvas-source-retrieve");
    expect(prompt).not.toContain("canvas-publish-create");
  });

  // The pattern hint exists for the legacy template ids the skill defines shapes
  // for. Every canvas created today is `freeform`, which names no shape — passing
  // it through would put "requested pattern" on every generation task.
  it.each([
    ["web-analytics", true],
    [FREEFORM_TEMPLATE_ID, false],
  ])("templateId=%s hints a pattern: %s", (templateId, hinted) => {
    const prompt = buildCanvasGenerationPrompt({ ...base, templateId });
    expect(prompt.includes("requested pattern:")).toBe(hinted);
    expect(prompt).not.toContain("WebOverviewQuery");
  });
});
