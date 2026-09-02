import type { SeriesKind } from "@posthog/ui/features/docs/hooks/dataPointSeries";
import { useDataPoint } from "@posthog/ui/features/docs/hooks/useDataPoint";
import {
  formatMetric,
  useInsightMetric,
} from "@posthog/ui/features/docs/hooks/useInsightMetric";
import {
  dataValueToBlock,
  replaceInlineWithBlock,
} from "@posthog/ui/features/docs/prosemirror/dataPointShape";
import { useEvidenceUrl } from "@posthog/ui/features/editor/components/EvidenceRefChip";
import { HighlightedCode } from "@posthog/ui/primitives/HighlightedCode";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { mergeAttributes, Node } from "@tiptap/core";
import {
  NodeViewWrapper,
  type ReactNodeViewProps,
  ReactNodeViewRenderer,
} from "@tiptap/react";
import type { ReactElement } from "react";
import { useEffect, useRef, useState } from "react";
import {
  DocRefCardAction,
  DocRefCardActions,
  DocRefHover,
} from "./inline/DocRefCard";

/**
 * A live data point in a sentence.
 *
 * The page stores the query behind it, never the figure, so the sentence tells
 * the truth every time it is read. A data point picked from a saved insight
 * keeps the insight instead, and reads the same way.
 */

export interface DataValueAttrs {
  /** A HogQL SELECT the page runs on every read. */
  query: string;
  /** A saved insight, for a number picked rather than asked for. */
  shortId: string;
  label: string;
  /** A caveat the agent added, shown on hover. */
  note: string;
  /** The request this answered, which is also its thread's key. */
  requestId: string;
  /** One cell reads as a number; a date column with a number column reads as a sparkline. */
  shape: "number" | "series";
}

const SPARK_W = 56;
const SPARK_H = 14;

interface ChartSize {
  width: number;
  height: number;
}

const INLINE: ChartSize = { width: SPARK_W, height: SPARK_H };

/** The line of a series. Small enough to sit in a sentence; larger in a card. */
export function Spark({
  points,
  size = INLINE,
  className = "doc-spark",
}: {
  points: number[];
  size?: ChartSize;
  className?: string;
}) {
  const { width, height } = size;
  const max = Math.max(...points);
  const min = Math.min(...points);
  const range = max - min || 1;
  const step = points.length > 1 ? width / (points.length - 1) : 0;
  const path = points
    .map((point, index) => {
      const x = (index * step).toFixed(1);
      const y = (height - 1.5 - ((point - min) / range) * (height - 3)).toFixed(
        1,
      );
      return `${index === 0 ? "M" : "L"}${x} ${y}`;
    })
    .join(" ");
  return (
    <svg
      className={className}
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      role="img"
      aria-label={`${points.length} points`}
    >
      <path d={path} fill="none" strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  );
}

/** The columns of a series of categories, one per row. */
function Columns({
  points,
  size = INLINE,
  className = "doc-spark doc-spark--columns",
}: {
  points: number[];
  size?: ChartSize;
  className?: string;
}) {
  const { width, height } = size;
  const max = Math.max(...points, 0) || 1;
  const gap = width > SPARK_W ? 4 : 1.5;
  const column = (width - gap * (points.length - 1)) / points.length;
  return (
    <svg
      className={className}
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      role="img"
      aria-label={`${points.length} categories`}
    >
      {points.map((point, index) => {
        const bar = Math.max(1, (Math.max(point, 0) / max) * height);
        return (
          <rect
            key={`${index}:${point}`}
            x={(index * (column + gap)).toFixed(1)}
            y={(height - bar).toFixed(1)}
            width={column.toFixed(1)}
            height={bar.toFixed(1)}
          />
        );
      })}
    </svg>
  );
}

const CARD_CHART: ChartSize = { width: 256, height: 64 };
/** Past this many columns the labels no longer fit under them. */
const MAX_LABELLED_COLUMNS = 6;

/** A day label reads as its day; a timestamp drops the time. */
function shortLabel(label: string): string {
  return label.replace(/[T ]\d{2}:\d{2}.*$/, "");
}

/** The chart a reader hovers into: the same points, big enough to read. */
function SeriesChart({
  points,
  labels,
  kind,
}: {
  points: number[];
  labels: string[];
  kind: SeriesKind;
}): ReactElement {
  const max = formatMetric(Math.max(...points));
  return (
    <div className="mt-2">
      <div className="text-(--gray-10) text-[10px] leading-none">{max}</div>
      <div className="mt-1 border-(--gray-5) border-b pb-px">
        {kind === "categories" ? (
          <Columns
            points={points}
            size={CARD_CHART}
            className="doc-card-chart doc-spark--columns"
          />
        ) : (
          <Spark points={points} size={CARD_CHART} className="doc-card-chart" />
        )}
      </div>
      {kind === "categories" ? (
        points.length <= MAX_LABELLED_COLUMNS ? (
          <div
            className="mt-1 grid gap-1 text-(--gray-10) text-[10px] leading-snug"
            style={{
              gridTemplateColumns: `repeat(${points.length}, minmax(0, 1fr))`,
            }}
          >
            {labels.map((label, index) => (
              <span
                key={`${index}-${label}`}
                className="truncate"
                title={label}
              >
                {label}
              </span>
            ))}
          </div>
        ) : null
      ) : (
        <div className="mt-1 flex justify-between text-(--gray-10) text-[10px] leading-snug">
          <span>{shortLabel(labels[0] ?? "")}</span>
          <span>{shortLabel(labels[labels.length - 1] ?? "")}</span>
        </div>
      )}
    </div>
  );
}

const LAND_MS = 1_200;

/** Marks a value that just arrived or just changed, without moving the page. */
function useLanding(query: string): boolean {
  const [landing, setLanding] = useState(false);
  const seen = useRef<string | null>(null);
  useEffect(() => {
    if (seen.current === null) {
      seen.current = query;
      return;
    }
    if (seen.current === query) return;
    seen.current = query;
    setLanding(true);
    const timer = setTimeout(() => setLanding(false), LAND_MS);
    return () => clearTimeout(timer);
  }, [query]);
  return landing;
}

interface FigureSource {
  /** The SQL behind the figure, or nothing for a saved insight. */
  query: string;
  shortId: string;
  /** Takes the figure out of the line and puts it under it as a block. */
  onConvert: (() => void) | null;
  /** Asks the page to keep rechecking this number and say when it moves. */
  onWatch: (() => void) | null;
}

function DataValueCard({
  label,
  note,
  error,
  points,
  labels,
  kind,
  source,
  close,
}: {
  label: string;
  note?: string;
  error?: string | null;
  points: number[];
  labels: string[];
  kind: SeriesKind | null;
  source: FigureSource;
  close: () => void;
}): ReactElement {
  const [showSql, setShowSql] = useState(false);
  const url = useEvidenceUrl(
    source.query ? "hogql" : "insight",
    source.query || source.shortId,
  );
  const footer =
    kind === "categories"
      ? `${points.length} categories, the total shown. Runs live on every read.`
      : kind === "time"
        ? `${points.length} points, the last one shown. Runs live on every read.`
        : "Runs live on every read.";
  return (
    <div className="w-72 p-2.5">
      <span className="line-clamp-2 block font-semibold text-[13px] leading-snug">
        {label}
      </span>
      {kind && points.length > 1 ? (
        <SeriesChart points={points} labels={labels} kind={kind} />
      ) : null}
      {note ? (
        <span className="mt-1.5 block text-(--gray-11) text-[11.5px] leading-snug">
          {note}
        </span>
      ) : null}
      {error ? (
        <span className="mt-1.5 block text-(--red-11) text-[11.5px] leading-snug">
          {error}
        </span>
      ) : null}
      <span className="mt-1.5 block text-(--gray-10) text-[10.5px]">
        {footer}
      </span>
      {showSql && source.query ? (
        <div className="mt-2 max-h-28 overflow-hidden whitespace-pre-wrap break-words font-mono text-[11.5px] leading-[1.5]">
          <HighlightedCode code={source.query} language="sql" />
        </div>
      ) : null}
      <DocRefCardActions>
        {source.onConvert ? (
          <DocRefCardAction
            onSelect={() => {
              source.onConvert?.();
              close();
            }}
          >
            {source.query ? "SQL card" : "Chart"}
          </DocRefCardAction>
        ) : null}
        {url ? (
          <DocRefCardAction
            onSelect={() => {
              openExternalUrl(url);
              close();
            }}
          >
            PostHog
          </DocRefCardAction>
        ) : null}
        {source.query ? (
          <DocRefCardAction onSelect={() => setShowSql((open) => !open)}>
            {showSql ? "Hide SQL" : "SQL"}
          </DocRefCardAction>
        ) : null}
        {source.onWatch ? (
          <DocRefCardAction
            onSelect={() => {
              source.onWatch?.();
              close();
            }}
          >
            Watch
          </DocRefCardAction>
        ) : null}
      </DocRefCardActions>
    </div>
  );
}

function Figure({
  value,
  points = [],
  isLoading,
  isError,
  label,
  note,
  error,
  landing,
  source,
  kind = null,
  labels = [],
}: {
  value: string;
  points?: number[];
  labels?: string[];
  isLoading: boolean;
  isError: boolean;
  label: string;
  note?: string;
  error?: string | null;
  landing?: boolean;
  source: FigureSource;
  kind?: SeriesKind | null;
}) {
  const showSpark = !isLoading && !isError && points.length > 1;
  return (
    <DocRefHover
      card={{
        title: label,
        render: (close) => (
          <DataValueCard
            label={label}
            note={note}
            error={isError ? error : null}
            points={showSpark ? points : []}
            labels={labels}
            kind={showSpark ? kind : null}
            source={source}
            close={close}
          />
        ),
      }}
      trigger={
        <span
          className={
            landing ? "doc-datavalue doc-datavalue--new" : "doc-datavalue"
          }
          data-state={isError ? "error" : undefined}
        >
          {showSpark && kind === "categories" ? (
            <Columns points={points} />
          ) : showSpark ? (
            <Spark points={points} />
          ) : null}
          {isLoading ? "…" : isError ? "—" : value}
        </span>
      }
    />
  );
}

function QueryFigure({
  query,
  label,
  note,
  shape,
  onConvert,
  onWatch,
}: {
  query: string;
  label: string;
  note: string;
  shape: "number" | "series";
  onConvert: (() => void) | null;
  onWatch: (() => void) | null;
}) {
  const point = useDataPoint(query, shape);
  const landing = useLanding(query);
  return (
    <Figure
      value={point.value}
      points={point.points}
      labels={point.labels}
      isLoading={point.isLoading}
      isError={point.isError}
      error={point.error}
      label={label || "Data point"}
      note={note}
      landing={landing}
      kind={point.seriesKind}
      source={{ query, shortId: "", onConvert, onWatch }}
    />
  );
}

function InsightFigure({
  shortId,
  label,
  onConvert,
}: {
  shortId: string;
  label: string;
  onConvert: (() => void) | null;
}) {
  const { value, isLoading, isError } = useInsightMetric(shortId);
  return (
    <Figure
      value={value}
      isLoading={isLoading}
      isError={isError}
      label={label || shortId}
      source={{ query: "", shortId, onConvert, onWatch: null }}
    />
  );
}

/** The page listens on its body for this; the node only knows its own element. */
export const WATCH_NUMBER_EVENT = "doc:watch-number";

export function DataValueView({ node, editor, getPos }: ReactNodeViewProps) {
  const attrs = node.attrs as DataValueAttrs;
  const { query, shortId, label, note, requestId, shape } = attrs;
  const wrapper = useRef<HTMLElement | null>(null);
  const onWatch =
    editor.isEditable && requestId && query
      ? () => {
          wrapper.current?.dispatchEvent(
            new CustomEvent(WATCH_NUMBER_EVENT, {
              bubbles: true,
              detail: { requestId, label: label || "Data point", query },
            }),
          );
        }
      : null;

  const onConvert = editor.isEditable
    ? () => {
        const pos = getPos();
        const json = dataValueToBlock(attrs);
        if (pos === undefined || !json) return;
        const tr = replaceInlineWithBlock(
          editor.state,
          pos,
          editor.schema.nodeFromJSON(json),
        );
        if (tr) editor.view.dispatch(tr);
      }
    : null;

  return (
    <NodeViewWrapper
      as="span"
      className="inline"
      data-request-id={requestId || undefined}
      ref={wrapper}
    >
      {query ? (
        <QueryFigure
          query={query}
          label={label}
          note={note ?? ""}
          shape={shape === "series" ? "series" : "number"}
          onConvert={onConvert}
          onWatch={onWatch}
        />
      ) : (
        <InsightFigure shortId={shortId} label={label} onConvert={onConvert} />
      )}
    </NodeViewWrapper>
  );
}

export const DataValue = Node.create({
  name: "dataValue",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,

  addAttributes() {
    return {
      query: { default: "" },
      shortId: { default: "" },
      label: { default: "" },
      note: { default: "" },
      requestId: { default: "" },
      shape: { default: "number" },
    };
  },

  parseHTML() {
    return [{ tag: "span[data-data-value]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["span", mergeAttributes(HTMLAttributes, { "data-data-value": "" })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(DataValueView);
  },
});
