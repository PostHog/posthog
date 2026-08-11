import { describe, expect, it } from "vitest";
import {
  deriveTaskPrChip,
  getPrChipAppearance,
  type PrChipStatus,
  type PrChipTone,
  prChipAccessibilityLabel,
} from "./prPresentation";

function task(output: Record<string, unknown> | null) {
  return { latest_run: { output } };
}

describe("deriveTaskPrChip", () => {
  it.each([
    ["pr_url", { pr_url: "https://github.com/PostHog/code/pull/2422" }],
    ["pr_urls", { pr_urls: ["https://github.com/PostHog/code/pull/2422"] }],
  ])("reads the PR from %s", (_field, output) => {
    expect(deriveTaskPrChip(task(output))).toEqual({
      url: "https://github.com/PostHog/code/pull/2422",
      number: 2422,
      label: "#2422",
    });
  });

  it("takes the first url when a run reports several PRs", () => {
    const chip = deriveTaskPrChip(
      task({
        pr_urls: [
          "https://github.com/PostHog/code/pull/2422",
          "https://github.com/PostHog/code/pull/2423",
        ],
      }),
    );

    expect(chip?.label).toBe("#2422");
  });

  it("normalizes a url carrying a tab suffix", () => {
    const chip = deriveTaskPrChip(
      task({ pr_url: "https://github.com/PostHog/code/pull/2422/files" }),
    );

    expect(chip?.url).toBe("https://github.com/PostHog/code/pull/2422");
  });

  it.each([
    ["there is no run", {}],
    ["the run has no output", task(null)],
    ["pr_urls is empty", task({ pr_urls: [] })],
    ["pr_url is blank", task({ pr_url: "" })],
    [
      "the url is an issue, not a PR",
      task({ pr_url: "https://github.com/PostHog/code/issues/42" }),
    ],
    [
      "the url isn't a GitHub url",
      task({ pr_url: "https://example.com/not-a-pr" }),
    ],
  ])("returns no chip when %s", (_label, input) => {
    expect(deriveTaskPrChip(input)).toBeNull();
  });
});

describe("getPrChipAppearance", () => {
  it.each<[string, PrChipStatus | null | undefined, PrChipTone, string | null]>(
    [
      ["an unresolved status", null, "gray", null],
      ["a missing status", undefined, "gray", null],
      [
        "an open PR",
        { state: "open", merged: false, draft: false },
        "green",
        "Open",
      ],
      [
        "a draft PR",
        { state: "open", merged: false, draft: true },
        "gray",
        "Draft",
      ],
      [
        "a closed PR",
        { state: "closed", merged: false, draft: false },
        "red",
        "Closed",
      ],
      [
        "a merged PR",
        { state: "closed", merged: true, draft: false },
        "purple",
        "Merged",
      ],
    ],
  )("tones %s as %s", (_label, status, tone, statusLabel) => {
    expect(getPrChipAppearance(status)).toEqual({ tone, statusLabel });
  });
});

describe("prChipAccessibilityLabel", () => {
  const chip = {
    url: "https://github.com/PostHog/code/pull/2422",
    number: 2422,
    label: "#2422",
  };

  it("names the PR state once it resolves", () => {
    expect(prChipAccessibilityLabel(chip, "Merged")).toBe(
      "Open merged pull request #2422",
    );
  });

  it("claims no state while it is unresolved", () => {
    expect(prChipAccessibilityLabel(chip, null)).toBe(
      "Open pull request #2422",
    );
  });
});
