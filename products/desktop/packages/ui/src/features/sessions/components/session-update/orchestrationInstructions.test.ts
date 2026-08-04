import { describe, expect, it } from "vitest";
import { extractCustomInstructions } from "./customInstructions";
import { extractOrchestrationInstructions } from "./orchestrationInstructions";

const ORCHESTRATION_BLOCK =
  "<orchestration_instructions>\nThe following system-generated instructions apply to this orchestrated child run. Follow them.\n\nReport progress with tasks-notify-parent.\n</orchestration_instructions>";
const CUSTOM_INSTRUCTIONS_BLOCK =
  "<user_custom_instructions>\nThe user has saved custom instructions that apply to all of their tasks. Follow them.\n\nAlways use tabs.\n</user_custom_instructions>";

describe("extractOrchestrationInstructions", () => {
  it("strips orchestration framing without changing genuine custom instructions", () => {
    const content = `${ORCHESTRATION_BLOCK}\n\nBuild the focused change\n\n${CUSTOM_INSTRUCTIONS_BLOCK}`;

    const orchestration = extractOrchestrationInstructions(content);
    expect(orchestration?.body).toContain("tasks-notify-parent");
    expect(orchestration?.stripped).toContain("Build the focused change");
    expect(orchestration?.stripped).toContain(CUSTOM_INSTRUCTIONS_BLOCK);

    const customInstructions = extractCustomInstructions(
      orchestration?.stripped ?? "",
    );
    expect(customInstructions?.body).toContain("Always use tabs.");
    expect(customInstructions?.stripped).toBe("Build the focused change");
  });

  it("preserves user-authored orchestration tag examples", () => {
    const content =
      "Render this example: <orchestration_instructions>report often</orchestration_instructions>";

    expect(extractOrchestrationInstructions(content)).toBeNull();
  });
});
