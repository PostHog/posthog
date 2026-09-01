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
  if (typeof label === "string" && label.trim()) return label.trim();
  const title = node.attrs?.title;
  if (typeof title === "string" && title.trim()) return title.trim();
  return "";
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
