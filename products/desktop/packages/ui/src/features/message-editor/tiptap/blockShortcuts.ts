import { Extension } from "@tiptap/core";
import type { EditorState } from "@tiptap/pm/state";

/** True when the caret sits at the very start of a list item's first block. */
function atListItemStart(state: EditorState): boolean {
  const { empty, $from } = state.selection;
  if (!empty || $from.parentOffset > 0 || $from.depth < 2) return false;
  return $from.node(-1).type.name === "listItem" && $from.index(-1) === 0;
}

/**
 * Enter is the send key, so the list and code-block keymaps StarterKit binds to
 * it never fire. Shift+Enter carries them instead: a new list item inside a
 * list, a newline inside a fence, its usual hard break everywhere else.
 */
export const BlockShortcuts = Extension.create({
  name: "blockShortcuts",

  addKeyboardShortcuts() {
    return {
      "Shift-Enter": () => {
        const { editor } = this;
        if (editor.isActive("codeBlock")) {
          return editor.commands.insertContent("\n");
        }
        if (!editor.isActive("listItem")) return false;
        return (
          editor.commands.splitListItem("listItem") ||
          editor.commands.liftListItem("listItem")
        );
      },

      // Backspace at the head of a bullet drops the bullet and keeps the line,
      // as every other composer does. The default joins the line into the item
      // above instead, which leaves no way to take a bullet off a line.
      Backspace: () => {
        const { editor } = this;
        if (!atListItemStart(editor.state)) return false;
        return (
          editor.commands.undoInputRule() ||
          editor.commands.liftListItem("listItem")
        );
      },
    };
  },
});
