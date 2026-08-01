import { extractCanvasInstructions } from "@posthog/ui/features/sessions/components/session-update/canvasInstructions";
import { describe, expect, it } from "vitest";
import { buildFreeformGenerationPrompt } from "./freeformPrompt";

describe("buildFreeformGenerationPrompt", () => {
  const base = {
    dashboardId: "dash-1",
    name: "Signups",
    channelName: "growth",
    instruction: "add a retention chart",
  };

  it("leads with the user's instruction and wraps the contract in a tag", () => {
    const prompt = buildFreeformGenerationPrompt(base);
    // The visible message is the bare instruction; the boilerplate lives in the tag.
    expect(prompt.startsWith("add a retention chart\n\n")).toBe(true);
    expect(prompt).toContain("<canvas_generation_instructions>");
    expect(prompt).toContain("</canvas_generation_instructions>");

    const extracted = extractCanvasInstructions(prompt);
    expect(extracted?.stripped).toBe("add a retention chart");
    // The authoring contract + publishing rules are collapsed into the tag body.
    expect(extracted?.body).toContain("PUBLISHING");
    expect(extracted?.body).toContain(
      "desktop-file-system-canvas-partial-update",
    );
  });

  it("folds the current code into the tag when editing", () => {
    const prompt = buildFreeformGenerationPrompt({
      ...base,
      currentCode: "export const App = () => null;",
    });
    const extracted = extractCanvasInstructions(prompt);
    expect(extracted?.stripped).toBe("add a retention chart");
    expect(extracted?.body).toContain("export const App = () => null;");
    expect(extracted?.body).toContain("Edit the freeform React canvas");
  });
});
