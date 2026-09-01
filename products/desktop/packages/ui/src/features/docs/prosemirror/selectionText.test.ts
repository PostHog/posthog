import { Schema } from "@tiptap/pm/model";
import { EditorState, TextSelection } from "@tiptap/pm/state";
import { describe, expect, it } from "vitest";
import { selectionText } from "./selectionText";

const schema = new Schema({
  nodes: {
    doc: { content: "block+" },
    paragraph: { group: "block", content: "inline*" },
    text: { group: "inline" },
    taskChip: {
      group: "inline",
      inline: true,
      atom: true,
      attrs: { label: { default: "" } },
    },
  },
});

const CHIP_LINE = [
  { type: "text", text: "Signups fell. " },
  { type: "taskChip", attrs: { label: "Which step loses people?" } },
];

function stateWith(
  content: object[],
  select: (size: number) => { from: number; to: number },
): EditorState {
  const doc = schema.nodeFromJSON({
    type: "doc",
    content: [{ type: "paragraph", content }],
  });
  const state = EditorState.create({ schema, doc });
  const { from, to } = select(doc.content.size - 1);
  return state.apply(
    state.tr.setSelection(TextSelection.create(state.doc, from, to)),
  );
}

describe("selectionText", () => {
  it("reads a chip's label as words", () => {
    const state = stateWith(CHIP_LINE, (end) => ({ from: 1, to: end }));
    expect(selectionText(state)).toBe("Signups fell. Which step loses people?");
  });

  it("reads the whole line from a caret", () => {
    const state = stateWith(CHIP_LINE, () => ({ from: 3, to: 3 }));
    expect(selectionText(state)).toBe("Signups fell. Which step loses people?");
  });

  it("reads only what is selected", () => {
    const state = stateWith([{ type: "text", text: "one two three" }], () => ({
      from: 1,
      to: 8,
    }));
    expect(selectionText(state)).toBe("one two");
  });
});
