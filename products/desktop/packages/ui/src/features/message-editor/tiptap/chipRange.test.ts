import { getSchema } from "@tiptap/core";
import { Node as PmNode } from "@tiptap/pm/model";
import StarterKit from "@tiptap/starter-kit";
import { describe, expect, it } from "vitest";
import { findChipRangeById } from "./chipRange";
import { MentionChipNode } from "./MentionChipNode";

const schema = getSchema([StarterKit, MentionChipNode]);

function chip(chipId: string | null) {
  return {
    type: "mentionChip",
    attrs: {
      type: "file",
      id: "/tmp/pasted.txt",
      label: "Pasted text #1 (2 lines)",
      pastedText: true,
      chipId,
    },
  };
}

function text(value: string) {
  return { type: "text", text: value };
}

function docOf(...content: object[]): PmNode {
  return PmNode.fromJSON(schema, {
    type: "doc",
    content: [{ type: "paragraph", content }],
  });
}

describe("findChipRangeById", () => {
  it.each([
    {
      name: "chip followed by a trailing space swallows the space",
      doc: docOf(chip("a"), text(" tail")),
      chipId: "a",
      expected: { from: 1, to: 3 },
    },
    {
      name: "chip at the end of the doc",
      doc: docOf(text("hi "), chip("a")),
      chipId: "a",
      expected: { from: 4, to: 5 },
    },
    {
      name: "chip followed by non-space text",
      doc: docOf(chip("a"), text("x")),
      chipId: "a",
      expected: { from: 1, to: 2 },
    },
    {
      name: "matching chip among several",
      doc: docOf(chip("a"), text(" "), chip("b"), text(" ")),
      chipId: "b",
      expected: { from: 3, to: 5 },
    },
    {
      name: "no chip with the requested id",
      doc: docOf(chip("a"), text(" ")),
      chipId: "missing",
      expected: null,
    },
    {
      name: "chip without a chipId attribute",
      doc: docOf(chip(null), text(" ")),
      chipId: "a",
      expected: null,
    },
  ])("$name", ({ doc, chipId, expected }) => {
    expect(findChipRangeById(doc, chipId)).toEqual(expected);
  });
});
