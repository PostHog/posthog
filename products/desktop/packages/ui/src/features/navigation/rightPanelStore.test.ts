import { beforeEach, describe, expect, it } from "vitest";
import {
  DEFAULT_RIGHT_PANEL_SIDE,
  type RightPanelSide,
  resolveArtifactMark,
  resolveExpandedWidth,
  resolveRightPanelSide,
  useRightPanelStore,
} from "./rightPanelStore";

describe("resolveRightPanelSide", () => {
  it.each<{
    name: string;
    stored: RightPanelSide | null | undefined;
    closedByDefault: boolean;
    isReviewOpen: boolean;
    expected: RightPanelSide | null;
  }>([
    {
      name: "an untouched session opens on the timeline",
      stored: undefined,
      closedByDefault: false,
      isReviewOpen: false,
      expected: "timeline",
    },
    {
      name: "a session opened after someone put the panel away stays closed",
      stored: undefined,
      closedByDefault: true,
      isReviewOpen: false,
      expected: null,
    },
    {
      name: "a session someone closed the panel on stays closed",
      stored: null,
      closedByDefault: false,
      isReviewOpen: false,
      expected: null,
    },
    {
      name: "a session keeps the panel it was left on",
      stored: "artifacts",
      closedByDefault: false,
      isReviewOpen: false,
      expected: "artifacts",
    },
    {
      name: "a session left on a panel keeps it even after a close elsewhere",
      stored: "artifacts",
      closedByDefault: true,
      isReviewOpen: false,
      expected: "artifacts",
    },
    {
      name: "a review opened from elsewhere shows the changes",
      stored: "comments",
      closedByDefault: false,
      isReviewOpen: true,
      expected: "changes",
    },
    {
      name: "a review opened on a session someone closed the panel on still shows",
      stored: null,
      closedByDefault: false,
      isReviewOpen: true,
      expected: "changes",
    },
    {
      name: "a review closed from elsewhere closes the panel it was showing in",
      stored: "changes",
      closedByDefault: false,
      isReviewOpen: false,
      expected: null,
    },
  ])("$name", ({ stored, closedByDefault, isReviewOpen, expected }) => {
    expect(
      resolveRightPanelSide({ stored, closedByDefault, isReviewOpen }),
    ).toBe(expected);
  });
});

describe("setSideForKey", () => {
  beforeEach(() => {
    useRightPanelStore.setState({ sideByKey: {}, closedByDefault: false });
  });

  /** What a session nobody has touched would open on right now. */
  const freshSessionSide = (): RightPanelSide | null =>
    resolveRightPanelSide({
      stored: undefined,
      closedByDefault: useRightPanelStore.getState().closedByDefault,
      isReviewOpen: false,
    });

  it.each<{
    name: string;
    sides: (RightPanelSide | null)[];
    expected: RightPanelSide | null;
  }>([
    {
      name: "closing a panel leaves the next session closed too",
      sides: [null],
      expected: null,
    },
    {
      name: "opening one again brings the next session's panel back",
      sides: [null, "comments"],
      expected: DEFAULT_RIGHT_PANEL_SIDE,
    },
    {
      // Changes rides the review store, so PR links and diff toggles open it
      // without anyone reaching for the column.
      name: "a review opening over a closed panel leaves it closed",
      sides: [null, "changes"],
      expected: null,
    },
  ])("$name", ({ sides, expected }) => {
    for (const side of sides) {
      useRightPanelStore.getState().setSideForKey("task-1", side);
    }
    expect(freshSessionSide()).toBe(expected);
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

describe("resolveExpandedWidth", () => {
  it.each<{
    name: string;
    stored: number | null;
    windowWidth: number;
    expected: number;
  }>([
    {
      name: "a drawer nobody has dragged takes three quarters of the window",
      stored: null,
      windowWidth: 1600,
      expected: 1200,
    },
    {
      name: "a dragged width is kept as it is",
      stored: 900,
      windowWidth: 1600,
      expected: 900,
    },
    {
      name: "a width dragged out on a wider window still fits this one",
      stored: 2400,
      windowWidth: 1600,
      expected: 1600,
    },
    {
      name: "a width dragged in past the panel's floor is held at it",
      stored: 120,
      windowWidth: 1600,
      expected: 280,
    },
    {
      name: "a window narrower than the floor gives all of itself",
      stored: 120,
      windowWidth: 200,
      expected: 200,
    },
  ])("$name", ({ stored, windowWidth, expected }) => {
    expect(resolveExpandedWidth(stored, windowWidth)).toBe(expected);
  });
});
