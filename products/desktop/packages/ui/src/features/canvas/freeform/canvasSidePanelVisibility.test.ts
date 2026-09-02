import { describe, expect, it } from "vitest";
import { canvasSidePanelVisibility } from "./canvasSidePanelVisibility";

const base = {
  interactive: false,
  hasContent: true,
  hasActiveTask: false,
  generatingPanelOpen: false,
  viewOpen: false,
  collapsed: false,
  hasCommentTask: true,
};

describe("canvasSidePanelVisibility", () => {
  it.each([
    ["editing a canvas with content", { interactive: true }, true, false],
    [
      "editing an empty canvas with a run in flight",
      { interactive: true, hasContent: false, hasActiveTask: true },
      true,
      false,
    ],
    [
      "generating in view mode",
      { hasActiveTask: true, generatingPanelOpen: true },
      true,
      false,
    ],
    ["viewing, dock never opened", {}, false, false],
    [
      "viewing, dock opened from the breadcrumb",
      { viewOpen: true },
      false,
      true,
    ],
    [
      "viewing, dock opened but minimized",
      { viewOpen: true, collapsed: true },
      false,
      false,
    ],
    [
      "viewing a canvas no task backs",
      { viewOpen: true, hasCommentTask: false },
      false,
      false,
    ],
  ])("%s", (_name, overrides, editing, viewing) => {
    expect(canvasSidePanelVisibility({ ...base, ...overrides })).toEqual({
      editing,
      viewing,
    });
  });
});
