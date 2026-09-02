import type { JSONContent } from "@tiptap/core";
import type { Node as PMNode } from "@tiptap/pm/model";
import type { EditorState, Transaction } from "@tiptap/pm/state";
import type { DataValueAttrs } from "../extensions/DataValue";
import type { ObjectBlockAttrs } from "../extensions/ObjectBlock";

/**
 * Takes an inline node out of its line and puts a block under that line.
 * The words around the node stay where they are.
 */
export function replaceInlineWithBlock(
  state: EditorState,
  pos: number,
  block: PMNode,
): Transaction | null {
  const inline = state.doc.nodeAt(pos);
  if (!inline || !inline.isInline) return null;
  const after = state.doc.resolve(pos).after();
  const tr = state.tr;
  tr.delete(pos, pos + inline.nodeSize);
  tr.insert(tr.mapping.map(after), block);
  return tr;
}

/** The block a data point becomes: its query as a SQL card, or its insight as a chart. */
export function dataValueToBlock(attrs: DataValueAttrs): JSONContent | null {
  const title = attrs.label || null;
  if (attrs.query) {
    return {
      type: "objectBlock",
      attrs: {
        mode: "hogql",
        query: attrs.query,
        title,
        caption: attrs.note || null,
        requestId: attrs.requestId || null,
      },
    };
  }
  if (attrs.shortId) {
    return {
      type: "objectBlock",
      attrs: { mode: "insight", shortId: attrs.shortId, title },
    };
  }
  return null;
}

/**
 * Puts a block's data point back into the text, on its own line under the
 * title it had. The shape is left to the result: one cell reads as a number, a
 * date column with a number column reads as a sparkline.
 */
export function replaceBlockWithInline(
  state: EditorState,
  pos: number,
): Transaction | null {
  const block = state.doc.nodeAt(pos);
  if (!block || block.type.name !== "objectBlock") return null;
  const attrs = block.attrs as ObjectBlockAttrs;
  if (!attrs.query && !attrs.shortId) return null;
  const { schema } = state;
  const value = schema.nodes.dataValue.create({
    query: attrs.mode === "hogql" ? (attrs.query ?? "") : "",
    shortId: attrs.mode === "insight" ? (attrs.shortId ?? "") : "",
    label: attrs.title ?? "",
    note: attrs.caption ?? "",
    requestId: attrs.requestId ?? "",
    shape: "series",
  });
  const line = attrs.title ? [schema.text(`${attrs.title}: `), value] : [value];
  return state.tr.replaceWith(
    pos,
    pos + block.nodeSize,
    schema.nodes.paragraph.create(null, line),
  );
}
