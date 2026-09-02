import type { EditorSelection } from "@posthog/ui/features/code-editor/components/CodeMirrorEditor";
import type { ArtifactHtmlFrameRect } from "./artifactHtmlFrameHost";

export function selectionAnchor(
  frame: ArtifactHtmlFrameRect,
  selection: ArtifactHtmlFrameRect,
): { top: number; endX: number; bottom: number } {
  return {
    top: frame.top + selection.top,
    endX: frame.left + selection.right,
    bottom: frame.top + selection.bottom,
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
