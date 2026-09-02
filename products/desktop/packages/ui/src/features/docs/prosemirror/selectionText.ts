import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import type { EditorState } from "@tiptap/pm/state";

/**
 * What a chip says, for code that reads a selection as words.
 *
 * A chip is one node holding a label, so plain text extraction skips it and a
 * line reading "compare this against @Anna's task" comes out as "compare this
 * against".
 */
function leafText(node: ProseMirrorNode): string {
  const label = node.attrs?.label;
  const title = node.attrs?.title;
  const words =
    typeof label === "string" && label.trim()
      ? label.trim()
      : typeof title === "string" && title.trim()
        ? title.trim()
        : "";
  if (!words) return "";
  // A live number reads as what it measures, marked so the sentence still scans:
  // "came to [signups last month], and" rather than words run into words.
  const isFigure =
    node.type.name === "dataValue" || node.type.name === "dataRequest";
  return isFigure ? `[${words}]` : words;
}

/**
 * The words a person has selected, or the whole line their caret is on.
 */
export function selectionText(state: EditorState): string {
  const { from, to } = state.selection;
  if (from !== to) return state.doc.textBetween(from, to, " ", leafText).trim();
  const position = state.doc.resolve(from);
  return state.doc
    .textBetween(position.start(), position.end(), " ", leafText)
    .trim();
}
