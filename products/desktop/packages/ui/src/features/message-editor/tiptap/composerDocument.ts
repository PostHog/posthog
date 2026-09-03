import { isBashModeText } from "@posthog/core/message-editor/paste";
import type { Editor } from "@tiptap/core";
import {
  Fragment,
  Node as ProseMirrorNode,
  type Schema,
} from "@tiptap/pm/model";
import { editorContentToTiptapJson } from "./markdownDoc";

/**
 * Recalled prompts, history entries and queued messages arrive as markdown, so
 * they get parsed back into nodes the way a restored draft does. Without this a
 * recalled list comes back as literal dashes.
 */
export function markdownFragment(schema: Schema, text: string): Fragment {
  try {
    const json = editorContentToTiptapJson({
      segments: [{ type: "text", text }],
    });
    return ProseMirrorNode.fromJSON(schema, json).content;
  } catch {
    return Fragment.from(
      schema.nodes.paragraph.create(null, schema.text(text)),
    );
  }
}

/**
 * `getText()` drops backticks and fences, so `!rm -rf` written as code reads as
 * a shell command. Bash mode needs the leading `!` to be plain text.
 */
export function isBashModeDoc(editor: Editor, text: string): boolean {
  if (!isBashModeText(text)) return false;
  const first = editor.state.doc.firstChild;
  if (first?.type.name !== "paragraph") return false;
  const leading = first.firstChild;
  return !leading?.marks.some((mark) => mark.type.name === "code");
}
