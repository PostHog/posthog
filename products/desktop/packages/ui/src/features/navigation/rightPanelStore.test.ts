import { describe, expect, it } from "vitest";
import { type RightPanelSide, resolveRightPanelSide } from "./rightPanelStore";

describe("resolveRightPanelSide", () => {
  it.each<{
    name: string;
    stored: RightPanelSide | null | undefined;
    isReviewOpen: boolean;
    expected: RightPanelSide | null;
  }>([
    {
      name: "an untouched session opens on the timeline",
      stored: undefined,
      isReviewOpen: false,
      expected: "timeline",
    },
    {
      name: "a session someone closed the panel on stays closed",
      stored: null,
      isReviewOpen: false,
      expected: null,
    },
    {
      name: "a session keeps the panel it was left on",
      stored: "artifacts",
      isReviewOpen: false,
      expected: "artifacts",
    },
    {
      name: "a review opened from elsewhere shows the changes",
      stored: "comments",
      isReviewOpen: true,
      expected: "changes",
    },
    {
      name: "a review opened on a session someone closed the panel on still shows",
      stored: null,
      isReviewOpen: true,
      expected: "changes",
    },
    {
      name: "a review closed from elsewhere closes the panel it was showing in",
      stored: "changes",
      isReviewOpen: false,
      expected: null,
    },
  ])("$name", ({ stored, isReviewOpen, expected }) => {
    expect(resolveRightPanelSide({ stored, isReviewOpen })).toBe(expected);
  });
});
