import type { EditorSelection } from "@posthog/ui/features/code-editor/components/CodeMirrorEditor";
import type { SelectionAnchor } from "@posthog/ui/features/code-editor/components/selectionScreenshot";
import type { ArtifactHtmlFrameRect } from "./artifactHtmlFrameHost";

export function selectionAnchor(
  frame: ArtifactHtmlFrameRect,
  selection: ArtifactHtmlFrameRect,
): SelectionAnchor {
  return {
    top: frame.top + selection.top,
    endX: frame.left + selection.right,
    bottom: frame.top + selection.bottom,
    bounds: {
      top: frame.top,
      left: frame.left,
      right: frame.right,
      bottom: frame.bottom,
    },
  };
}

export function withSelectionPosition(
  current: EditorSelection | null,
  frame: ArtifactHtmlFrameRect,
  selection: ArtifactHtmlFrameRect,
): EditorSelection | null {
  return current
    ? {
        ...current,
        anchor: selectionAnchor(frame, selection),
      }
    : null;
}
