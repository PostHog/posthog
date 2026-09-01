import { getSchema } from "@tiptap/core";
import Bold from "@tiptap/extension-bold";
import Document from "@tiptap/extension-document";
import Paragraph from "@tiptap/extension-paragraph";
import Text from "@tiptap/extension-text";
import { describe, expect, it } from "vitest";
import { pruneUnknown } from "./pruneUnknown";

const schema = getSchema([Document, Paragraph, Text, Bold]);

describe("pruneUnknown", () => {
  // A page that names a node this build dropped used to render as an empty
  // page, because ProseMirror refuses the whole document. Losing someone's
  // writing on a schema change is the worst thing a document product can do.
  it("keeps the page when one node type is gone", () => {
    const pruned = pruneUnknown(
      {
        type: "doc",
        content: [
          {
            type: "paragraph",
            content: [
              { type: "text", text: "before " },
              { type: "ghostChip", attrs: { id: "1" } },
              { type: "text", text: "after" },
            ],
          },
        ],
      },
      schema,
    );

    expect(pruned).toEqual({
      type: "doc",
      content: [
        {
          type: "paragraph",
          content: [
            { type: "text", text: "before " },
            { type: "text", text: "after" },
          ],
        },
      ],
    });
  });

  it("lifts the children of an unknown wrapper", () => {
    const pruned = pruneUnknown(
      {
        type: "doc",
        content: [
          {
            type: "ghostColumns",
            content: [
              { type: "paragraph", content: [{ type: "text", text: "kept" }] },
            ],
          },
        ],
      },
      schema,
    );

    expect(pruned).toEqual({
      type: "doc",
      content: [
        { type: "paragraph", content: [{ type: "text", text: "kept" }] },
      ],
    });
  });

  it("drops a mark the schema lost and keeps the text", () => {
    const pruned = pruneUnknown(
      {
        type: "doc",
        content: [
          {
            type: "paragraph",
            content: [
              {
                type: "text",
                text: "words",
                marks: [{ type: "bold" }, { type: "ghostMark" }],
              },
            ],
          },
        ],
      },
      schema,
    );

    expect(pruned).toEqual({
      type: "doc",
      content: [
        {
          type: "paragraph",
          content: [{ type: "text", text: "words", marks: [{ type: "bold" }] }],
        },
      ],
    });
  });
});
