import { beforeEach, describe, expect, it } from "vitest";
import {
  DEFAULT_RIGHT_PANEL_SIDE,
  type RightPanelSide,
  resolveArtifactMark,
  resolvePanelDrag,
  resolvePanelWidth,
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

describe("resolvePanelWidth", () => {
  it.each<{
    name: string;
    stored: number;
    rowWidth: number;
    expected: number;
  }>([
    {
      name: "a dragged width is kept as it is",
      stored: 900,
      rowWidth: 1600,
      expected: 900,
    },
    {
      name: "a drag to the row's far edge stops short of covering it",
      stored: 1600,
      rowWidth: 1600,
      expected: 1550,
    },
    {
      name: "a width dragged out on a wider window still fits this row",
      stored: 2400,
      rowWidth: 1600,
      expected: 1550,
    },
    {
      name: "a width dragged in past the panel's floor is held at it",
      stored: 120,
      rowWidth: 1600,
      expected: 280,
    },
    {
      name: "a row with less room than the floor gives what it has",
      stored: 120,
      rowWidth: 200,
      expected: 150,
    },
  ])("$name", ({ stored, rowWidth, expected }) => {
    expect(resolvePanelWidth(stored, rowWidth)).toBe(expected);
  });
});

describe("resolvePanelDrag", () => {
  // A 1600px row: the panel's ceiling is 1550, its floor 280, and the drag
  // closes below 140 / reopens at 156.
  const rowWidth = 1600;

  it.each<{
    name: string;
    pointer: number;
    open: boolean;
    expanded: boolean;
    expected: ReturnType<typeof resolvePanelDrag>;
  }>([
    {
      name: "dragging an open panel sets the width the pointer asks for",
      pointer: 700,
      open: true,
      expanded: false,
      expected: { action: "resize", width: 700 },
    },
    {
      name: "dragging an open panel past its floor closes it",
      pointer: 100,
      open: true,
      expanded: false,
      expected: { action: "close" },
    },
    {
      name: "dragging back out while still held brings it in again",
      pointer: 200,
      open: false,
      expanded: false,
      expected: { action: "reopen", width: 280 },
    },
    {
      name: "a closed panel between the two lines stays closed",
      pointer: 150,
      open: false,
      expanded: false,
      expected: { action: "hold" },
    },
    {
      name: "dragging an expanded panel in takes it off the full row",
      pointer: 900,
      open: true,
      expanded: true,
      expected: { action: "collapse", width: 900 },
    },
    {
      name: "dragging an expanded panel out asks for room it hasn't got",
      pointer: 1900,
      open: true,
      expanded: true,
      expected: { action: "hold" },
    },
    {
      name: "an expanded panel dragged past its floor collapses on the way",
      pointer: 100,
      open: true,
      expanded: true,
      expected: { action: "collapse", width: 280 },
    },
  ])("$name", ({ pointer, open, expanded, expected }) => {
    expect(resolvePanelDrag({ pointer, rowWidth, open, expanded })).toEqual(
      expected,
    );
  });
});
