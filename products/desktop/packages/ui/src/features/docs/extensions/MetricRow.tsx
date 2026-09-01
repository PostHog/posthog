import { MessageChartCard } from "@posthog/ui/features/editor/components/MessageChartCard";
import { chartBlockKey } from "@posthog/ui/utils/chartBlocks";
import { mergeAttributes, Node } from "@tiptap/core";
import {
  NodeViewWrapper,
  type ReactNodeViewProps,
  ReactNodeViewRenderer,
} from "@tiptap/react";

/**
 * A row of numbers a doc keeps in view.
 *
 * Each tile is a saved insight, rendered through the same card pipeline as a
 * single chart block. The node holds only the references.
 */

export interface MetricRowItem {
  label: string;
  shortId: string;
}

export interface MetricRowAttrs {
  items: MetricRowItem[];
}

export function MetricRowView({ node }: ReactNodeViewProps) {
  const { items } = node.attrs as MetricRowAttrs;
  const tiles = Array.isArray(items) ? items : [];

  if (tiles.length === 0) {
    return (
      <NodeViewWrapper className="my-3">
        <div className="rounded-(--radius-3) border border-(--gray-6) p-3 text-(--gray-11) text-sm">
          This row has no numbers yet. Add an insight to it.
        </div>
      </NodeViewWrapper>
    );
  }

  return (
    <NodeViewWrapper className="my-3" data-drag-handle>
      <div className="@container">
        <div className="grid @3xl:grid-cols-3 @md:grid-cols-2 grid-cols-1 gap-3">
          {tiles.map((item) => (
            <MessageChartCard
              key={item.shortId}
              spec={{
                mode: "insight",
                shortId: item.shortId,
                title: item.label,
              }}
              blockKey={chartBlockKey(`metric-${item.shortId}`)}
            />
          ))}
        </div>
      </div>
    </NodeViewWrapper>
  );
}

export const MetricRow = Node.create({
  name: "metricRow",
  group: "block",
  atom: true,
  draggable: true,
  selectable: true,

  addAttributes() {
    return { items: { default: [] } };
  },

  parseHTML() {
    return [{ tag: "div[data-metric-row]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-metric-row": "" })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(MetricRowView);
  },
});
