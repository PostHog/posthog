import { Extension } from "@tiptap/core";

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
    };
  },
});
