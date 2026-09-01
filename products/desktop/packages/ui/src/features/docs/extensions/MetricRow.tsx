import { useInsightMetric } from "@posthog/ui/features/docs/hooks/useInsightMetric";
import { mergeAttributes, Node } from "@tiptap/core";
import {
  NodeViewWrapper,
  type ReactNodeViewProps,
  ReactNodeViewRenderer,
} from "@tiptap/react";

/**
 * A row of numbers the page keeps in view.
 *
 * Each tile is a saved insight, read live and shown as a plain number. A row of
 * charts would drown the prose around it, so the row stays numeric and the full
 * chart lives in its own block.
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
      <NodeViewWrapper className="my-4">
        <div className="rounded-(--radius-3) border border-(--gray-6) p-3 text-(--gray-11) text-sm">
          This row has no numbers yet. Add an insight to it.
        </div>
      </NodeViewWrapper>
    );
  }

  return (
    <NodeViewWrapper className="my-5" data-drag-handle>
      <div className="doc-metrics">
        {tiles.map((item) => (
          <MetricTile key={item.shortId} item={item} />
        ))}
      </div>
    </NodeViewWrapper>
  );
}

function MetricTile({ item }: { item: MetricRowItem }) {
  const { value, isLoading, isError } = useInsightMetric(item.shortId);

  return (
    <div className="py-1">
      <div className="doc-metric-label">{item.label}</div>
      <div className="doc-metric-value">
        {isLoading ? "…" : isError ? "—" : value}
      </div>
    </div>
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
