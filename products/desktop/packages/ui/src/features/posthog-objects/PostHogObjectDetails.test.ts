import { describe, expect, it } from "vitest";
import { foldSections } from "./PostHogObjectDetails";

describe("foldSections", () => {
  it("keeps a single-field section under its own heading, not a neighbor's", () => {
    // The default experiment shape: a one-field Metrics section sits between two
    // multi-field sections. Folding it onto the last card mislabeled the metric
    // as a variant, so each section must keep its own heading and fields.
    const folded = foldSections([
      {
        title: "Configuration",
        fields: [
          { label: "Type", value: "Multivariate" },
          { label: "Release conditions", value: "1 condition" },
        ],
      },
      { title: "Metrics", fields: [{ label: "Metric 1", value: "Signups" }] },
      {
        title: "Variants",
        fields: [
          { label: "control", value: "50% rollout" },
          { label: "test", value: "50% rollout" },
        ],
      },
    ]);
    expect(folded.map((section) => section.title)).toEqual([
      "Configuration",
      "Metrics",
      "Variants",
    ]);
    expect(
      folded.find((section) => section.title === "Metrics")?.fields,
    ).toEqual([{ label: "Metric 1", value: "Signups" }]);
    expect(
      folded.find((section) => section.title === "Variants")?.fields,
    ).toEqual([
      { label: "control", value: "50% rollout" },
      { label: "test", value: "50% rollout" },
    ]);
  });

  it("merges sections that share a heading into one card", () => {
    const folded = foldSections([
      {
        title: "Release conditions",
        fields: [{ label: "Set 1", value: "plan is pro" }],
      },
      {
        title: "Release conditions",
        fields: [{ label: "Set 2", value: "country is US" }],
      },
    ]);
    expect(folded).toEqual([
      {
        title: "Release conditions",
        fields: [
          { label: "Set 1", value: "plan is pro" },
          { label: "Set 2", value: "country is US" },
        ],
      },
    ]);
  });
});
