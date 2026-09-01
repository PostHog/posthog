import { EvidenceRefChip } from "@posthog/ui/features/editor/components/EvidenceRefChip";
import { mergeAttributes, Node } from "@tiptap/core";
import {
  NodeViewWrapper,
  type ReactNodeViewProps,
  ReactNodeViewRenderer,
} from "@tiptap/react";

/**
 * A PostHog object, inline in a doc: an insight, a flag, an experiment, a
 * replay, a support ticket, anything in the object-kind registry.
 *
 * The node stores only the kind and the id. The chip, its hover preview, and
 * the click-through are the same ones agent messages use.
 */

export interface ObjectChipAttrs {
  kind: string;
  objectId: string;
  label: string;
}

export function ObjectChipView({ node }: ReactNodeViewProps) {
  const { kind, objectId, label } = node.attrs as ObjectChipAttrs;
  return (
    <NodeViewWrapper as="span" className="inline-block align-baseline">
      <EvidenceRefChip target={{ kind, id: objectId }}>
        {label || objectId}
      </EvidenceRefChip>
    </NodeViewWrapper>
  );
}

export const ObjectChip = Node.create({
  name: "objectChip",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,

  addAttributes() {
    return {
      kind: { default: "" },
      objectId: { default: "" },
      label: { default: "" },
    };
  },

  parseHTML() {
    return [{ tag: "span[data-object-chip]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "span",
      mergeAttributes(HTMLAttributes, { "data-object-chip": "" }),
      HTMLAttributes.label ?? "",
    ];
  },

  addNodeView() {
    return ReactNodeViewRenderer(ObjectChipView);
  },
});
