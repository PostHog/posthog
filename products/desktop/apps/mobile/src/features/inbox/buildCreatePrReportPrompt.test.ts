import { describe, expect, it } from "vitest";
import { buildCreatePrReportPrompt } from "./buildCreatePrReportPrompt";

const BASE =
  "Act on this signal report. Investigate the root cause, implement the fix, and open a PR if appropriate.";
const FEEDBACK_PREFIX =
  "Additional feedback from the user (take this into account, including any questions raised in the report thread):";

describe("buildCreatePrReportPrompt", () => {
  it.each([
    {
      name: "returns the base prompt unchanged when no feedback is given",
      input: { summary: "A summary" },
      expected: `${BASE}\n\nA summary`,
    },
    {
      name: "appends a feedback section when feedback is provided",
      input: { summary: "A summary", feedback: "Use the staging database" },
      expected: `${BASE}\n\nA summary\n\n${FEEDBACK_PREFIX}\nUse the staging database`,
    },
    {
      name: "trims feedback before appending it",
      input: { summary: "A summary", feedback: "  Use the staging database  " },
      expected: `${BASE}\n\nA summary\n\n${FEEDBACK_PREFIX}\nUse the staging database`,
    },
    {
      name: "treats whitespace-only feedback as no feedback",
      input: { summary: "A summary", feedback: "   " },
      expected: `${BASE}\n\nA summary`,
    },
    {
      name: "tolerates a missing summary",
      input: {},
      expected: `${BASE}\n\n`,
    },
  ])("$name", ({ input, expected }) => {
    expect(buildCreatePrReportPrompt(input)).toBe(expected);
  });
});
