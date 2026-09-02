import { ArrowDownRightIcon, ArrowUpRightIcon } from "@phosphor-icons/react";
import { useInsightMetric } from "@posthog/ui/features/docs/hooks/useInsightMetric";
import { useEvidenceUrl } from "@posthog/ui/features/editor/components/EvidenceRefChip";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { mergeAttributes, Node } from "@tiptap/core";
import {
  NodeViewWrapper,
  type ReactNodeViewProps,
  ReactNodeViewRenderer,
} from "@tiptap/react";
import type { ReactElement } from "react";
import { DocRefHover } from "./inline/DocRefCard";

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

const SPARK_W = 40;
const SPARK_H = 14;

/** A hairline of the series, quiet enough to sit under a number in prose. */
function MetricSparkline({ points }: { points: number[] }): ReactElement {
  const max = Math.max(...points);
  const min = Math.min(...points);
  const range = max - min || 1;
  const line = points
    .map((point, index) => {
      const x = (index / (points.length - 1)) * SPARK_W;
      const y = SPARK_H - 1 - ((point - min) / range) * (SPARK_H - 2);
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg
      viewBox={`0 0 ${SPARK_W} ${SPARK_H}`}
      width={SPARK_W}
      height={SPARK_H}
      className="mt-1 block"
      role="img"
      aria-label="Trend"
    >
      <path
        d={line}
        fill="none"
        stroke="var(--gray-a7)"
        strokeWidth={1}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function MetricDelta({ delta }: { delta: number }): ReactElement {
  const rising = delta >= 0;
  const Arrow = rising ? ArrowUpRightIcon : ArrowDownRightIcon;
  const percent = Math.abs(delta * 100);
  return (
    // Neither direction is colored: a doc does not know whether up is good.
    <span className="doc-metric-delta">
      <Arrow size={10} weight="bold" aria-hidden />
      {percent < 10 ? percent.toFixed(1) : Math.round(percent)}%
    </span>
  );
}

export interface MetricTileState {
  label: string;
  value: string;
  series: number[] | null;
  delta: number | null;
  isLoading: boolean;
  isError: boolean;
  /** Where the insight lives in PostHog, for a tile that has nothing to show. */
  url?: string | null;
}

/** One number in the row, with nothing to fetch. */
export function MetricTileView({
  label,
  value,
  series,
  delta,
  isLoading,
  isError,
  url = null,
}: MetricTileState): ReactElement {
  const empty = isError || value === "—";
  return (
    <div className="py-1">
      <div className="doc-metric-label">{label}</div>
      {isLoading ? (
        <div className="doc-metric-value-loading">
          <span className="sr-only">Loading</span>
        </div>
      ) : (
        <div className="doc-metric-value">
          {empty ? (
            <DocRefHover
              card={{
                title: label,
                meta: isError
                  ? "This number could not be loaded."
                  : "This insight has no single number.",
                action: url
                  ? {
                      label: "Open in PostHog",
                      onSelect: () => openExternalUrl(url),
                    }
                  : undefined,
              }}
              trigger={<span className="doc-metric-empty">—</span>}
            />
          ) : (
            value
          )}
          {delta !== null ? <MetricDelta delta={delta} /> : null}
        </div>
      )}
      {series ? <MetricSparkline points={series} /> : null}
    </div>
  );
}

function MetricTile({ item }: { item: MetricRowItem }) {
  const metric = useInsightMetric(item.shortId);
  const url = useEvidenceUrl("insight", item.shortId);
  return <MetricTileView label={item.label} url={url} {...metric} />;
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
