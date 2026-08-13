import { describe, expect, it } from "vitest";
import { type RightPanelSide, resolveRightPanelSide } from "./rightPanelStore";

describe("resolveRightPanelSide", () => {
  it.each<{
    name: string;
    stored: RightPanelSide | null | undefined;
    hasTask: boolean;
    isReviewOpen: boolean;
    expected: RightPanelSide | null;
  }>([
    {
      name: "an untouched session opens on the timeline",
      stored: undefined,
      hasTask: true,
      isReviewOpen: false,
      expected: "timeline",
    },
    {
      name: "a session someone closed the panel on stays closed",
      stored: null,
      hasTask: true,
      isReviewOpen: false,
      expected: null,
    },
    {
      name: "a session keeps the panel it was left on",
      stored: "artifacts",
      hasTask: true,
      isReviewOpen: false,
      expected: "artifacts",
    },
    {
      name: "a review opened from elsewhere shows the changes",
      stored: "comments",
      hasTask: true,
      isReviewOpen: true,
      expected: "changes",
    },
    {
      name: "a review opened on a session someone closed the panel on still shows",
      stored: null,
      hasTask: true,
      isReviewOpen: true,
      expected: "changes",
    },
    {
      name: "no session leaves the column closed",
      stored: undefined,
      hasTask: false,
      isReviewOpen: false,
      expected: null,
    },
  ])("$name", ({ stored, hasTask, isReviewOpen, expected }) => {
    expect(resolveRightPanelSide({ stored, hasTask, isReviewOpen })).toBe(
      expected,
    );
  });
});
