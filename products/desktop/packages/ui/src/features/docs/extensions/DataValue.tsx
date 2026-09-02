import { Tooltip, TooltipContent, TooltipTrigger } from "@posthog/quill";
import { useDataPoint } from "@posthog/ui/features/docs/hooks/useDataPoint";
import { useInsightMetric } from "@posthog/ui/features/docs/hooks/useInsightMetric";
import { mergeAttributes, Node } from "@tiptap/core";
import {
  NodeViewWrapper,
  type ReactNodeViewProps,
  ReactNodeViewRenderer,
} from "@tiptap/react";
import { useEffect, useRef, useState } from "react";

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

function Figure({
  value,
  isLoading,
  isError,
  label,
  detail,
  note,
  error,
  landing,
}: {
  value: string;
  isLoading: boolean;
  isError: boolean;
  label: string;
  /** The query or the insight behind the figure. */
  detail: string;
  note?: string;
  error?: string | null;
  landing?: boolean;
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span
            className={
              landing ? "doc-datavalue doc-datavalue--new" : "doc-datavalue"
            }
            data-state={isError ? "error" : undefined}
          />
        }
      >
        {isLoading ? "…" : isError ? "—" : value}
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-sm">
        {/* The tooltip is dark whatever the theme, so its greys are picked for it. */}
        <div className="flex flex-col gap-1.5 text-left">
          <span className="font-medium">{label}</span>
          {note ? <span className="text-(--gray-5)">{note}</span> : null}
          {isError && error ? (
            <span className="text-(--red-9)">{error}</span>
          ) : null}
          <code className="max-h-28 overflow-hidden whitespace-pre-wrap break-words font-mono text-(--gray-6) text-[11.5px] leading-[1.5]">
            {detail}
          </code>
          <span className="text-(--gray-8) text-[11px]">
            Runs live on every read
          </span>
        </div>
      </TooltipContent>
    </Tooltip>
  );
}

function QueryFigure({
  query,
  label,
  note,
}: {
  query: string;
  label: string;
  note: string;
}) {
  const point = useDataPoint(query);
  const landing = useLanding(query);
  return (
    <Figure
      value={point.value}
      isLoading={point.isLoading}
      isError={point.isError}
      error={point.error}
      label={label || "Data point"}
      detail={query}
      note={note}
      landing={landing}
    />
  );
}

function InsightFigure({ shortId, label }: { shortId: string; label: string }) {
  const { value, isLoading, isError } = useInsightMetric(shortId);
  return (
    <Figure
      value={value}
      isLoading={isLoading}
      isError={isError}
      label={label || shortId}
      detail={`Saved insight ${shortId}`}
    />
  );
}

export function DataValueView({ node }: ReactNodeViewProps) {
  const { query, shortId, label, note, requestId } =
    node.attrs as DataValueAttrs;

  return (
    <NodeViewWrapper
      as="span"
      className="inline"
      data-request-id={requestId || undefined}
    >
      {query ? (
        <QueryFigure query={query} label={label} note={note ?? ""} />
      ) : (
        <InsightFigure shortId={shortId} label={label} />
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
