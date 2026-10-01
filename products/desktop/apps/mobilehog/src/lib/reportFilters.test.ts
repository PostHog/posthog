import { describe, expect, it } from "vitest";
import { reportFilterParams } from "./reportFilters";

describe("reportFilterParams", () => {
  it.each([
    [
      "attention",
      {
        status: "ready,pending_input",
        actionability: "immediately_actionable,requires_human_input",
        ordering: "status,-priority,-created_at",
      },
    ],
    [
      "pull-requests",
      {
        status: "ready",
        has_implementation_pr: true,
        ordering: "status,-priority,-created_at",
      },
    ],
    ["dismissed", { status: "suppressed,resolved", ordering: "-updated_at" }],
  ] as const)("maps %s to its list params", (filter, params) => {
    expect(reportFilterParams(filter)).toEqual(params);
  });
});
