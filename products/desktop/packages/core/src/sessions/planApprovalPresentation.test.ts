import { describe, expect, it } from "vitest";
import { extractPlanText } from "./planApprovalPresentation";

describe("extractPlanText", () => {
  it.each([
    [{ rawInput: { plan: "Raw plan" } }, "Raw plan"],
    [{ content: [{ text: "Direct content" }] }, "Direct content"],
    [
      {
        content: [
          { type: "content", content: { type: "text", text: "Nested" } },
        ],
      },
      "Nested",
    ],
    [{ rawInput: {}, content: [] }, null],
  ])("extracts plan presentation from %o", (toolCall, expected) => {
    expect(extractPlanText(toolCall)).toBe(expected);
  });

  it("prefers streamed content over stale raw input", () => {
    expect(
      extractPlanText({
        rawInput: { plan: "Canonical" },
        content: [{ text: "Rendered" }],
      }),
    ).toBe("Rendered");
  });
});
