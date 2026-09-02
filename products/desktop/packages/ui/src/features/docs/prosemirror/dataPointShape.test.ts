import { Schema } from "@tiptap/pm/model";
import { EditorState } from "@tiptap/pm/state";
import { describe, expect, it } from "vitest";
import {
  dataValueToBlock,
  replaceBlockWithInline,
  replaceInlineWithBlock,
} from "./dataPointShape";

const schema = new Schema({
  nodes: {
    doc: { content: "block+" },
    paragraph: { group: "block", content: "inline*" },
    text: { group: "inline" },
    dataValue: {
      group: "inline",
      inline: true,
      atom: true,
      attrs: {
        query: { default: "" },
        shortId: { default: "" },
        label: { default: "" },
        note: { default: "" },
        requestId: { default: "" },
        shape: { default: "number" },
      },
    },
    objectBlock: {
      group: "block",
      atom: true,
      attrs: {
        mode: { default: "insight" },
        shortId: { default: null },
        query: { default: null },
        title: { default: null },
        caption: { default: null },
        requestId: { default: null },
      },
    },
  },
});

describe("dataPointShape", () => {
  it.each([
    {
      name: "a query becomes a SQL card and keeps its thread",
      attrs: {
        query: "select count() from events",
        shortId: "",
        label: "Events",
        note: "Excludes test accounts",
        requestId: "req-1",
        shape: "number" as const,
      },
      block: {
        mode: "hogql",
        query: "select count() from events",
        title: "Events",
        caption: "Excludes test accounts",
        requestId: "req-1",
      },
    },
    {
      name: "an insight becomes a chart",
      attrs: {
        query: "",
        shortId: "abc123",
        label: "",
        note: "",
        requestId: "",
        shape: "number" as const,
      },
      block: { mode: "insight", shortId: "abc123", title: null },
    },
  ])("$name", ({ attrs, block }) => {
    const json = dataValueToBlock(attrs);
    expect(json?.attrs).toEqual(block);

    const doc = schema.node("doc", null, [
      schema.node("paragraph", null, [
        schema.text("Events this week: "),
        schema.node("dataValue", {
          query: attrs.query,
          shortId: attrs.shortId,
        }),
        schema.text("."),
      ]),
      schema.node("paragraph", null, [schema.text("Next line.")]),
    ]);
    const state = EditorState.create({ doc });
    const tr = replaceInlineWithBlock(
      state,
      1 + "Events this week: ".length,
      schema.nodeFromJSON(json),
    );

    expect(tr?.doc.toJSON()).toEqual({
      type: "doc",
      content: [
        {
          type: "paragraph",
          content: [{ type: "text", text: "Events this week: ." }],
        },
        { type: "objectBlock", attrs: expect.objectContaining(block) },
        { type: "paragraph", content: [{ type: "text", text: "Next line." }] },
      ],
    });
  });

  it("puts a SQL card back into the text under its title", () => {
    const doc = schema.node("doc", null, [
      schema.node("paragraph", null, [schema.text("Daily events:")]),
      schema.node("objectBlock", {
        mode: "hogql",
        query: "select day, n from daily",
        title: "events per day",
        caption: "UTC",
        requestId: "req-2",
      }),
    ]);
    const tr = replaceBlockWithInline(EditorState.create({ doc }), 15);

    expect(tr?.doc.toJSON().content[1]).toEqual({
      type: "paragraph",
      content: [
        { type: "text", text: "events per day: " },
        {
          type: "dataValue",
          attrs: {
            query: "select day, n from daily",
            shortId: "",
            label: "events per day",
            note: "UTC",
            requestId: "req-2",
            shape: "series",
          },
        },
      ],
    });
  });

  it("does nothing when the position holds no inline node", () => {
    const doc = schema.node("doc", null, [
      schema.node("paragraph", null, [schema.text("Words")]),
    ]);
    const state = EditorState.create({ doc });
    expect(
      replaceInlineWithBlock(state, 0, schema.node("objectBlock")),
    ).toBeNull();
  });
});
