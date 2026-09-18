import { Editor } from "@tiptap/core";
import { TextSelection } from "@tiptap/pm/state";
import { describe, expect, it } from "vitest";
import { getEditorExtensions } from "./extensions";
import {
  editorContentToTiptapJson,
  tiptapJsonToEditorContent,
} from "./markdownDoc";

function makeEditor(markdown?: string): Editor {
  const element = document.createElement("div");
  document.body.appendChild(element);
  const editor = new Editor({
    element,
    extensions: getEditorExtensions({ sessionId: "session-1" }),
  });
  if (markdown !== undefined) {
    editor.commands.setContent(
      editorContentToTiptapJson({
        segments: [{ type: "text", text: markdown }],
      }),
    );
  }
  return editor;
}

function press(editor: Editor, key: string, shiftKey = false): boolean {
  return (
    editor.view.someProp("handleKeyDown", (fn) =>
      fn(editor.view, new KeyboardEvent("keydown", { key, shiftKey })),
    ) ?? false
  );
}

/** Puts the caret at either end of the first text node starting with `text`. */
function caretAt(editor: Editor, text: string, side: "before" | "after"): void {
  let pos: number | null = null;
  editor.state.doc.descendants((node, at) => {
    if (pos !== null || !node.isText || !node.text?.startsWith(text)) return;
    pos = side === "before" ? at : at + node.nodeSize;
  });
  if (pos === null) throw new Error(`no text node starting with ${text}`);
  editor.view.dispatch(
    editor.state.tr.setSelection(TextSelection.create(editor.state.doc, pos)),
  );
}

function markdown(editor: Editor): string {
  return tiptapJsonToEditorContent(editor.getJSON())
    .segments.map((segment) => (segment.type === "text" ? segment.text : ""))
    .join("");
}

describe("block shortcuts", () => {
  it.each([
    ["the first bullet", "- alpha\n- beta", "alpha", "alpha\n\n- beta"],
    [
      "a bullet in the middle",
      "- alpha\n- beta\n- gamma",
      "beta",
      "- alpha\n\nbeta\n\n- gamma",
    ],
    [
      "a nested bullet, one level per press",
      "- alpha\n    - nested",
      "nested",
      "- alpha\n- nested",
    ],
  ])(
    "backspace at the head of %s takes the bullet off the line",
    (_name, source, target, expected) => {
      const editor = makeEditor(source);
      caretAt(editor, target, "before");
      expect(press(editor, "Backspace")).toBe(true);
      expect(markdown(editor)).toBe(expected);
    },
  );

  it("removes the empty bullet that shift+enter adds, keeping the line", () => {
    const editor = makeEditor("- alpha");
    caretAt(editor, "alpha", "after");
    press(editor, "Enter", true);
    expect(press(editor, "Backspace")).toBe(true);
    editor.commands.insertContent("plain line");
    expect(markdown(editor)).toBe("- alpha\n\nplain line");
  });

  it("leaves backspace inside a bullet to the browser", () => {
    const editor = makeEditor("- alpha");
    caretAt(editor, "alpha", "after");
    expect(press(editor, "Backspace")).toBe(false);
    expect(markdown(editor)).toBe("- alpha");
  });
});
