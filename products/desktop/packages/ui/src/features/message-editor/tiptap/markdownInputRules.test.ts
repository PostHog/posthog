import { Editor } from "@tiptap/core";
import { describe, expect, it } from "vitest";
import { getEditorExtensions } from "./extensions";
import { tiptapJsonToEditorContent } from "./markdownDoc";

/** Stands in for a Shift+Enter press inside the typed strings below. */
const BREAK = "\n";

function makeEditor(): Editor {
  const element = document.createElement("div");
  document.body.appendChild(element);
  return new Editor({
    element,
    extensions: getEditorExtensions({ sessionId: "session-1" }),
  });
}

/** Types character by character so input rules see the stream a user produces. */
function type(editor: Editor, input: string): void {
  for (const char of input) {
    if (char === BREAK) {
      editor.view.someProp("handleKeyDown", (fn) =>
        fn(
          editor.view,
          new KeyboardEvent("keydown", { key: "Enter", shiftKey: true }),
        ),
      );
      continue;
    }
    const { from, to } = editor.state.selection;
    const insert = () => editor.state.tr.insertText(char, from, to);
    const handled = editor.view.someProp("handleTextInput", (fn) =>
      fn(editor.view, from, to, char, insert),
    );
    if (!handled) {
      editor.view.dispatch(insert());
    }
  }
}

function markdown(editor: Editor): string {
  return tiptapJsonToEditorContent(editor.getJSON())
    .segments.map((segment) => (segment.type === "text" ? segment.text : ""))
    .join("");
}

describe("markdown input rules", () => {
  it.each([
    ["bullet on the first line", `* milk${BREAK}eggs`, "- milk\n- eggs"],
    [
      "bullet after a hard break",
      `hello${BREAK}* milk${BREAK}eggs`,
      "hello\n\n- milk\n- eggs",
    ],
    [
      "numbered list after a hard break",
      `intro${BREAK}3. three`,
      "intro\n\n3. three",
    ],
    [
      "code fence after a hard break",
      `look:${BREAK}\`\`\`ts const a = 1`,
      "look:\n\n```ts\nconst a = 1\n```",
    ],
    ["a star that is not a marker", "2 * 3 = 6", "2 * 3 = 6"],
    ["a star mid-line", `hello${BREAK}a * b`, "hello  \na * b"],
    ["inline code mid-line", "run `pnpm dev` now", "run `pnpm dev` now"],
    [
      "inline code after a hard break",
      `hello${BREAK}\`pnpm dev\` now`,
      "hello  \n`pnpm dev` now",
    ],
    ["a lone backtick", "a ` b", "a ` b"],
  ])("%s", (_name, typed, expected) => {
    const editor = makeEditor();
    type(editor, typed);
    expect(markdown(editor)).toBe(expected);
  });
});
