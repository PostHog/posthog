import { Editor } from "@tiptap/core";
import { describe, expect, it } from "vitest";
import { isBashModeDoc, markdownFragment } from "./composerDocument";
import { getEditorExtensions } from "./extensions";
import { tiptapJsonToEditorContent } from "./markdownDoc";

function makeEditor(): Editor {
  const element = document.createElement("div");
  document.body.appendChild(element);
  return new Editor({
    element,
    extensions: getEditorExtensions({ sessionId: "session-1" }),
  });
}

function setMarkdown(editor: Editor, text: string): void {
  const fragment = markdownFragment(editor.schema, text);
  editor.view.dispatch(
    editor.state.tr.replaceWith(0, editor.state.doc.content.size, fragment),
  );
}

function markdown(editor: Editor): string {
  return tiptapJsonToEditorContent(editor.getJSON())
    .segments.map((segment) => (segment.type === "text" ? segment.text : ""))
    .join("");
}

describe("composer document helpers", () => {
  it.each([
    ["a list", "- milk\n- eggs"],
    ["a fenced block", "```ts\nconst a = 1\n```"],
    ["prose", "just some words"],
  ])("recalls %s as the markdown it was sent as", (_name, text) => {
    const editor = makeEditor();
    setMarkdown(editor, text);
    expect(markdown(editor)).toBe(text);
  });

  it.each([
    ["plain text", "!ls", true],
    ["inline code", "`!ls`", false],
    ["a fenced block", "```\n!ls\n```", false],
    ["a list", "- !ls", false],
  ])("reads %s as bash mode: %s", (_name, text, expected) => {
    const editor = makeEditor();
    setMarkdown(editor, text);
    expect(isBashModeDoc(editor, editor.getText())).toBe(expected);
  });
});
