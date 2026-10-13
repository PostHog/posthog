import { Editor } from "@tiptap/core";
import { describe, expect, it } from "vitest";
import { getEditorExtensions } from "./extensions";
import { tiptapJsonToEditorContent } from "./markdownDoc";
import { insertPastedMarkdown } from "./markdownPaste";

function makeEditor(): Editor {
  const element = document.createElement("div");
  document.body.appendChild(element);
  return new Editor({
    element,
    extensions: getEditorExtensions({ sessionId: "session-1" }),
  });
}

function markdown(editor: Editor): string {
  return tiptapJsonToEditorContent(editor.getJSON())
    .segments.map((segment) => (segment.type === "text" ? segment.text : ""))
    .join("");
}

describe("pasted markdown", () => {
  it.each([
    ["a bullet list", "- milk\n- eggs", "- milk\n- eggs"],
    ["a numbered list", "1. one\n2. two", "1. one\n2. two"],
    ["a nested list", "- milk\n  - skimmed", "- milk\n  - skimmed"],
    [
      "a fenced code block",
      "look:\n\n```ts\nconst a = 1\n```",
      "look:\n\n```ts\nconst a = 1\n```",
    ],
    ["inline code", "run `pnpm dev` now", "run `pnpm dev` now"],
  ])("%s becomes nodes", (_name, pasted, expected) => {
    const editor = makeEditor();
    expect(insertPastedMarkdown(editor.view, pasted)).toBe(true);
    expect(markdown(editor)).toBe(expected);
  });

  it.each([
    ["prose", "just some words"],
    ["prose over two lines", "first line\nsecond line"],
  ])("leaves %s to the default paste", (_name, pasted) => {
    const editor = makeEditor();
    expect(insertPastedMarkdown(editor.view, pasted)).toBe(false);
  });

  it("leaves a paste inside a code block literal", () => {
    const editor = makeEditor();
    editor.commands.setContent({
      type: "doc",
      content: [{ type: "codeBlock", content: [{ type: "text", text: "x" }] }],
    });
    editor.commands.setTextSelection(2);
    expect(insertPastedMarkdown(editor.view, "- milk\n- eggs")).toBe(false);
  });

  it("keeps text already in the paragraph", () => {
    const editor = makeEditor();
    editor.commands.insertContent("shopping:");
    expect(insertPastedMarkdown(editor.view, "\n- milk\n- eggs")).toBe(true);
    expect(markdown(editor)).toBe("shopping:\n\n- milk\n- eggs");
  });
});
