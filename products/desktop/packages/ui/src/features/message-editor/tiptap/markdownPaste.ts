import type { JSONContent } from "@tiptap/core";
import { Node as ProseMirrorNode, Slice } from "@tiptap/pm/model";
import type { EditorView } from "@tiptap/pm/view";
import { editorContentToTiptapJson } from "./markdownDoc";

function hasCodeMark(node: JSONContent): boolean {
  return (node.marks ?? []).some((mark) => mark.type === "code");
}

/**
 * Plain paragraphs are what the default paste already produces, so only
 * markdown that turns into list, code-block or inline-code nodes is worth
 * taking over the paste for.
 */
function hasMarkdownNodes(node: JSONContent): boolean {
  if (node.type === "bulletList") return true;
  if (node.type === "orderedList") return true;
  if (node.type === "codeBlock") return true;
  if (hasCodeMark(node)) return true;
  return (node.content ?? []).some(hasMarkdownNodes);
}

/**
 * Insert pasted markdown as real nodes. Input rules only fire on typing, so
 * without this a pasted `- milk` stays a literal dash.
 *
 * Returns false when the text carries no markdown, or when the caret sits in a
 * code block, leaving the paste to ProseMirror's default text handling.
 */
export function insertPastedMarkdown(view: EditorView, text: string): boolean {
  if (!text.trim()) return false;
  if (view.state.selection.$from.parent.type.spec.code) return false;

  const json = editorContentToTiptapJson({
    segments: [{ type: "text", text }],
  });
  if (!(json.content ?? []).some(hasMarkdownNodes)) return false;

  let doc: ProseMirrorNode;
  try {
    doc = ProseMirrorNode.fromJSON(view.state.schema, json);
  } catch {
    return false;
  }

  // Open ends let a leading or trailing paragraph merge into the paragraph the
  // caret is in, rather than splitting it.
  const openStart = doc.firstChild?.type.name === "paragraph" ? 1 : 0;
  const openEnd = doc.lastChild?.type.name === "paragraph" ? 1 : 0;
  view.dispatch(
    view.state.tr
      .replaceSelection(new Slice(doc.content, openStart, openEnd))
      .scrollIntoView(),
  );
  return true;
}
