import { mergeAttributes, Node } from "@tiptap/core";
import { ReactNodeViewRenderer } from "@tiptap/react";
import { DocInlineRef } from "./DocInlineRef";
import type { InlineRefKind } from "./types";

/**
 * Turns a kind into the TipTap node the editor registers.
 *
 * The node view is always `DocInlineRef`, so a new kind inherits the
 * underline, the selection ring, the hover card, and the click.
 */
export function createInlineRef<A>(kind: InlineRefKind<A>): Node {
  const base =
    kind.base ??
    Node.create({
      name: kind.name,
      group: "inline",
      inline: true,
      atom: true,
      selectable: true,
    });

  return base.extend({
    name: kind.name,
    group: "inline",
    inline: true,
    atom: true,
    selectable: true,

    addAttributes() {
      return kind.attributes;
    },

    parseHTML() {
      return [{ tag: kind.parseTag }];
    },

    renderHTML({ node, HTMLAttributes }) {
      const attrs = node.attrs as A;
      return [
        "span",
        mergeAttributes(HTMLAttributes, kind.domAttributes(attrs)),
        kind.fallbackLabel(attrs),
      ];
    },

    addNodeView() {
      return ReactNodeViewRenderer((props) => (
        <DocInlineRef kind={kind} {...props} />
      ));
    },
  });
}
