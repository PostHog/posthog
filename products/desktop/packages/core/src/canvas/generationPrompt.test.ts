import { describe, expect, it } from "vitest";
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

  it("includes a requested template pattern without adding authoring rules", () => {
    const prompt = buildCanvasGenerationPrompt({
      ...base,
      templateId: "web-analytics",
    });
    expect(prompt).toContain('requested pattern: "web-analytics"');
    expect(prompt).not.toContain("WebOverviewQuery");
  });
});
