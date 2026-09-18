import type { EditorContent } from "@posthog/core/message-editor/content";
import type { JSONContent } from "@tiptap/core";
import { describe, expect, it } from "vitest";
import {
  editorContentToTiptapJson,
  tiptapJsonToEditorContent,
} from "./markdownDoc";

function text(content: EditorContent): string {
  return content.segments
    .map((segment) => (segment.type === "text" ? segment.text : "@chip"))
    .join("");
}

function doc(...content: JSONContent[]): JSONContent {
  return { type: "doc", content };
}

function paragraph(...content: JSONContent[]): JSONContent {
  return { type: "paragraph", content };
}

function item(...content: JSONContent[]): JSONContent {
  return { type: "listItem", content };
}

describe("markdownDoc", () => {
  it.each([
    [
      "bullet list",
      doc({
        type: "bulletList",
        content: [
          item(paragraph({ type: "text", text: "milk" })),
          item(paragraph({ type: "text", text: "eggs" })),
        ],
      }),
      "- milk\n- eggs",
    ],
    [
      "nested bullet list",
      doc({
        type: "bulletList",
        content: [
          item(paragraph({ type: "text", text: "eggs" }), {
            type: "bulletList",
            content: [item(paragraph({ type: "text", text: "free range" }))],
          }),
        ],
      }),
      "- eggs\n  - free range",
    ],
    [
      "ordered list",
      doc({
        type: "orderedList",
        attrs: { start: 1 },
        content: [
          item(paragraph({ type: "text", text: "first" })),
          item(paragraph({ type: "text", text: "second" })),
        ],
      }),
      "1. first\n2. second",
    ],
    [
      "code block",
      doc({
        type: "codeBlock",
        attrs: { language: "ts" },
        content: [{ type: "text", text: "const a = 1\nconst b = 2" }],
      }),
      "```ts\nconst a = 1\nconst b = 2\n```",
    ],
    [
      "paragraph before a list",
      doc(paragraph({ type: "text", text: "shopping" }), {
        type: "bulletList",
        content: [item(paragraph({ type: "text", text: "milk" }))],
      }),
      "shopping\n\n- milk",
    ],
    [
      "hard break inside a paragraph",
      doc(
        paragraph(
          { type: "text", text: "one" },
          { type: "hardBreak" },
          { type: "text", text: "two" },
        ),
      ),
      "one  \ntwo",
    ],
    [
      "inline code",
      doc(
        paragraph(
          { type: "text", text: "run " },
          { type: "text", text: "pnpm dev", marks: [{ type: "code" }] },
        ),
      ),
      "run `pnpm dev`",
    ],
  ])("serializes %s to markdown", (_name, json, expected) => {
    expect(text(tiptapJsonToEditorContent(json))).toBe(expected);
  });

  it.each([
    ["bullet list", "- milk\n- eggs"],
    ["nested bullet list", "- eggs\n  - free range"],
    ["ordered list", "1. first\n2. second"],
    ["code block", "```ts\nconst a = 1\n```"],
    ["list after a paragraph", "shopping\n\n- milk\n- eggs"],
    ["list before a paragraph", "- milk\n\ndone"],
    ["hard break inside a paragraph", "one  \ntwo"],
    ["two paragraphs", "one\n\ntwo"],
    ["inline code", "run `pnpm dev` now"],
    ["inline code inside a list item", "- run `pnpm dev`"],
    ["backticks inside a fence", "```\na = `b`\n```"],
  ])("round-trips %s through the document model", (_name, markdown) => {
    const parsed = editorContentToTiptapJson({
      segments: [{ type: "text", text: markdown }],
    });
    expect(text(tiptapJsonToEditorContent(parsed))).toBe(markdown);
  });

  it("keeps mention chips attached to the list item they sit in", () => {
    const parsed = editorContentToTiptapJson({
      segments: [
        { type: "text", text: "- look at " },
        {
          type: "chip",
          chip: { type: "file", id: "/src/app.ts", label: "src/app.ts" },
        },
        { type: "text", text: "\n- then ship" },
      ],
    });

    const list = parsed.content?.[0];
    expect(list?.type).toBe("bulletList");
    expect(list?.content).toHaveLength(2);
    expect(list?.content?.[0].content?.[0].content?.[1]).toMatchObject({
      type: "mentionChip",
      attrs: { id: "/src/app.ts" },
    });
  });

  it("treats a lone marker as text, not a list", () => {
    const parsed = editorContentToTiptapJson({
      segments: [{ type: "text", text: "2 * 3 = 6" }],
    });

    expect(parsed.content?.[0].type).toBe("paragraph");
  });

  it("returns an empty paragraph for empty content", () => {
    expect(editorContentToTiptapJson({ segments: [] })).toEqual(
      doc(paragraph()),
    );
  });
});
