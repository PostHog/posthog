import { MessageChartCard } from "@posthog/ui/features/editor/components/MessageChartCard";
import type { ChartBlockSpec } from "@posthog/ui/utils/chartBlocks";
import { chartBlockKey } from "@posthog/ui/utils/chartBlocks";
import { mergeAttributes, Node } from "@tiptap/core";
import {
  NodeViewWrapper,
  type ReactNodeViewProps,
  ReactNodeViewRenderer,
} from "@tiptap/react";

/**
 * A live chart in a doc: a saved insight, a SQL query, or a session replay.
 *
 * The node stores the reference (or the query text), never the numbers, and
 * renders through the same card pipeline as agent messages and reports, so the
 * same query shows the same result everywhere.
 */

export interface ObjectBlockAttrs {
  mode: "insight" | "hogql" | "replay";
  shortId: string | null;
  query: string | null;
  sessionId: string | null;
  title: string | null;
  caption: string | null;
}

function toSpec(attrs: ObjectBlockAttrs): ChartBlockSpec | null {
  const shared = {
    title: attrs.title ?? undefined,
    caption: attrs.caption ?? undefined,
  };
  if (attrs.mode === "insight" && attrs.shortId) {
    return { mode: "insight", shortId: attrs.shortId, ...shared };
  }
  if (attrs.mode === "hogql" && attrs.query) {
    return { mode: "hogql", query: attrs.query, ...shared };
  }
  if (attrs.mode === "replay" && attrs.sessionId) {
    return { mode: "replay", sessionId: attrs.sessionId, ...shared };
  }
  return null;
}

export function ObjectBlockView({ node }: ReactNodeViewProps) {
  const spec = toSpec(node.attrs as ObjectBlockAttrs);

  return (
    <NodeViewWrapper className="my-3" data-drag-handle>
      {spec ? (
        <MessageChartCard
          spec={spec}
          blockKey={chartBlockKey(JSON.stringify(spec))}
        />
      ) : (
        <div className="rounded-(--radius-3) border border-(--gray-6) p-3 text-(--gray-11) text-sm">
          This block lost the thing it pointed at. Delete it and add the chart
          again.
        </div>
      )}
    </NodeViewWrapper>
  );
}

export const ObjectBlock = Node.create({
  name: "objectBlock",
  group: "block",
  atom: true,
  draggable: true,
  selectable: true,

  addAttributes() {
    return {
      mode: { default: "insight" },
      shortId: { default: null },
      query: { default: null },
      sessionId: { default: null },
      title: { default: null },
      caption: { default: null },
    };
  },

  parseHTML() {
    return [{ tag: "div[data-object-block]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "div",
      mergeAttributes(HTMLAttributes, { "data-object-block": "" }),
    ];
  },

  addNodeView() {
    return ReactNodeViewRenderer(ObjectBlockView);
  },
});
