import type { EditorSelection } from "@posthog/ui/features/code-editor/components/CodeMirrorEditor";
import { describe, expect, it } from "vitest";
import { withSelectionPosition } from "./artifactHtmlCommentPosition";

const selection = {
  text: "selected text",
  fromLine: 1,
  toLine: 13,
  anchor: { top: 110, endX: 230, bottom: 120 },
} satisfies EditorSelection;

const frame = {
  top: 100,
  left: 200,
  right: 600,
  bottom: 500,
  width: 400,
  height: 400,
};

describe("withSelectionPosition", () => {
  it("keeps the composer attached to its frame-relative selection", () => {
    expect(
      withSelectionPosition(selection, frame, {
        top: -20,
        left: 10,
        right: 30,
        bottom: -10,
        width: 20,
        height: 10,
      }),
    ).toEqual({
      ...selection,
      anchor: { top: 80, endX: 230, bottom: 90 },
    });
  });
});
