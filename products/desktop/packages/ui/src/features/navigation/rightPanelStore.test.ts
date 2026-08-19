import { describe, expect, it } from "vitest";
import {
  type RightPanelSide,
  resolveArtifactMark,
  resolveRightPanelSide,
} from "./rightPanelStore";

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

describe("resolveArtifactMark", () => {
  it.each<{
    name: string;
    count: number;
    seen: number | undefined;
    isShowingArtifacts: boolean;
    ready: boolean;
    markSeen: boolean;
    hasNew: boolean;
  }>([
    {
      name: "a session drawn for the first time takes what it has as seen",
      count: 3,
      seen: undefined,
      isShowingArtifacts: false,
      ready: true,
      markSeen: true,
      hasNew: false,
    },
    {
      name: "an artifact arriving after that marks the button",
      count: 4,
      seen: 3,
      isShowingArtifacts: false,
      ready: true,
      markSeen: false,
      hasNew: true,
    },
    {
      name: "an open artifacts panel keeps up with what arrives",
      count: 4,
      seen: 3,
      isShowingArtifacts: true,
      ready: true,
      markSeen: true,
      hasNew: false,
    },
    {
      name: "a dismissed file leaves nothing to announce",
      count: 2,
      seen: 3,
      isShowingArtifacts: false,
      ready: true,
      markSeen: false,
      hasNew: false,
    },
    {
      // The count reads zero before a manifest source loads; taking it as seen
      // would make the real files look new once they arrive.
      name: "a count still loading is not taken as seen",
      count: 0,
      seen: undefined,
      isShowingArtifacts: false,
      ready: false,
      markSeen: false,
      hasNew: false,
    },
  ])(
    "$name",
    ({ count, seen, isShowingArtifacts, ready, markSeen, hasNew }) => {
      expect(
        resolveArtifactMark({ count, seen, isShowingArtifacts, ready }),
      ).toEqual({
        markSeen,
        hasNew,
      });
    },
  );
});
