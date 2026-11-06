import { describe, expect, it } from "vitest";
import {
  canvasVersionNavigation,
  freshReadyDraftId,
  shouldClearCanvasBrowse,
} from "./canvasVersionNavigation";

// Newest first, matching the versions endpoint: v4 is the latest publish.
const VERSIONS = [{ id: "v4" }, { id: "v3" }, { id: "v2" }, { id: "v1" }];

describe("canvasVersionNavigation", () => {
  it("at the head: undo steps older, no redo", () => {
    const nav = canvasVersionNavigation({
      versions: VERSIONS,
      headVersionId: "v4",
      browseVersionId: null,
    });
    expect(nav).toEqual({
      headIndex: 0,
      currentIndex: 0,
      canUndo: true,
      canRedo: false,
      undoTargetId: "v3",
      redoTargetId: null,
    });
  });

  it("head mid-list after a revert: undo goes older, no redo while not browsing", () => {
    const nav = canvasVersionNavigation({
      versions: VERSIONS,
      headVersionId: "v2",
      browseVersionId: null,
    });
    expect(nav.headIndex).toBe(2);
    expect(nav.currentIndex).toBe(2);
    expect(nav.canUndo).toBe(true);
    expect(nav.undoTargetId).toBe("v1");
    // Versions newer than the reverted head are reachable via browse, not redo.
    expect(nav.canRedo).toBe(false);
  });

  it("browsing older than the head: undo and redo both step", () => {
    const nav = canvasVersionNavigation({
      versions: VERSIONS,
      headVersionId: "v4",
      browseVersionId: "v2",
    });
    expect(nav.currentIndex).toBe(2);
    expect(nav.canUndo).toBe(true);
    expect(nav.undoTargetId).toBe("v1");
    expect(nav.canRedo).toBe(true);
    expect(nav.redoTargetId).toBe("v3");
  });

  it("browsing at the oldest version: no further undo", () => {
    const nav = canvasVersionNavigation({
      versions: VERSIONS,
      headVersionId: "v4",
      browseVersionId: "v1",
    });
    expect(nav.canUndo).toBe(false);
    expect(nav.undoTargetId).toBeNull();
    expect(nav.canRedo).toBe(true);
  });

  it("redo onto the head clears the browse (null target)", () => {
    const nav = canvasVersionNavigation({
      versions: VERSIONS,
      headVersionId: "v4",
      browseVersionId: "v3",
    });
    expect(nav.canRedo).toBe(true);
    expect(nav.redoTargetId).toBeNull();
  });

  it("browsing newer than a mid-list head: undo steps back toward it, no redo", () => {
    // Redo only steps newer while browsing OLDER than the head; from a
    // version newer than a reverted head the way back is undo (toward the
    // head) or revert.
    const nav = canvasVersionNavigation({
      versions: VERSIONS,
      headVersionId: "v2",
      browseVersionId: "v3",
    });
    expect(nav.currentIndex).toBe(1);
    expect(nav.canRedo).toBe(false);
    expect(nav.canUndo).toBe(true);
    expect(nav.undoTargetId).toBe("v2");
  });

  it.each([
    ["unknown head id falls back to the top", "vX", null, 0, 0],
    ["missing head id falls back to the top", null, null, 0, 0],
    ["unknown browse id falls back to the head", "v3", "vX", 1, 1],
  ])("%s", (_name, headVersionId, browseVersionId, headIndex, currentIndex) => {
    const nav = canvasVersionNavigation({
      versions: VERSIONS,
      headVersionId,
      browseVersionId,
    });
    expect(nav.headIndex).toBe(headIndex);
    expect(nav.currentIndex).toBe(currentIndex);
  });

  it("empty history: nothing to step through", () => {
    const nav = canvasVersionNavigation({
      versions: [],
      headVersionId: null,
      browseVersionId: null,
    });
    expect(nav.canUndo).toBe(false);
    expect(nav.canRedo).toBe(false);
    expect(nav.undoTargetId).toBeNull();
  });
});

// Guards the auto-open contract: a draft opens exactly once, when its build
// first turns ready, and never for drafts that were already built (mount) or
// still building.
describe("freshReadyDraftId", () => {
  const seen = new Set(["d-old"]);

  it.each([
    [
      "newly ready draft",
      [{ versionId: "d-new", buildStatus: "ready" }],
      "d-new",
    ],
    [
      "already-seen ready draft",
      [{ versionId: "d-old", buildStatus: "ready" }],
      null,
    ],
    [
      "draft still building",
      [{ versionId: "d-new", buildStatus: "building" }],
      null,
    ],
    [
      "newest fresh draft wins (list is newest first)",
      [
        { versionId: "d-new", buildStatus: "ready" },
        { versionId: "d-older", buildStatus: "ready" },
      ],
      "d-new",
    ],
  ] as const)("%s → %s", (_name, drafts, expected) => {
    expect(freshReadyDraftId(seen, [...drafts])).toBe(expected);
  });
});

describe("shouldClearCanvasBrowse", () => {
  const VERSION_IDS = VERSIONS.map((v) => v.id);

  it.each([
    ["no browse", null, false, VERSION_IDS, false],
    ["browse still in the list", "v2", false, VERSION_IDS, false],
    ["browse pruned from the list", "vX", false, VERSION_IDS, true],
    ["still loading is not absence", "vX", true, VERSION_IDS, false],
    ["empty targets is not absence", "vX", false, [], false],
    // A staged draft is a valid target even though it is not a published version.
    [
      "draft is a valid target",
      "draft-1",
      false,
      [...VERSION_IDS, "draft-1"],
      false,
    ],
  ] as const)(
    "%s → %s",
    (_name, browseVersionId, loading, browseTargetIds, expected) => {
      expect(
        shouldClearCanvasBrowse({
          browseTargetIds: [...browseTargetIds],
          loading,
          browseVersionId,
        }),
      ).toBe(expected);
    },
  );
});
