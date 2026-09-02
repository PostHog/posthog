import {
  ArrowSquareOutIcon,
  CaretDownIcon,
  CaretRightIcon,
  PencilSimpleIcon,
} from "@phosphor-icons/react";
import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { useEvidenceUrl } from "@posthog/ui/features/editor/components/EvidenceRefChip";
import { MessageChartCard } from "@posthog/ui/features/editor/components/MessageChartCard";
import { HighlightedCode } from "@posthog/ui/primitives/HighlightedCode";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import type { ChartBlockSpec } from "@posthog/ui/utils/chartBlocks";
import { chartBlockKey } from "@posthog/ui/utils/chartBlocks";
import { mergeAttributes, Node } from "@tiptap/core";
import {
  NodeViewWrapper,
  type ReactNodeViewProps,
  ReactNodeViewRenderer,
} from "@tiptap/react";
import { useEffect, useRef, useState } from "react";

/**
 * A live chart in a doc: a saved insight, a SQL query, or a session replay.
 *
 * The node stores the reference (or the query text), never the numbers, and
 * renders through the same card pipeline as agent messages and reports, so the
 * same query shows the same result everywhere. A SQL query is written in the
 * block itself; nothing about adding a chart opens a window.
 */

export interface ObjectBlockAttrs {
  mode: "insight" | "hogql" | "replay";
  shortId: string | null;
  query: string | null;
  sessionId: string | null;
  title: string | null;
  caption: string | null;
  /** The data request this block answered, which is also its thread's key. */
  requestId: string | null;
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

const SQL_PLACEHOLDER = "select count() from events where event = '$pageview'";

/** The query on one line, for the head of a block that keeps the rest folded. */
function oneLine(query: string): string {
  return query.replace(/\s+/g, " ").trim();
}

function SqlEditor({
  initial,
  canCancel,
  onRun,
  onCancel,
}: {
  initial: string;
  canCancel: boolean;
  onRun: (query: string) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState(initial);
  const input = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    input.current?.focus();
  }, []);
  const ready = draft.trim().length > 0;
  const run = () => {
    if (ready) onRun(draft.trim());
  };
  return (
    <div className="doc-sql-card">
      <div className="doc-sql-head">SQL</div>
      <div className="doc-sql-editor">
        <HighlightedCode
          code={draft ? `${draft}\n` : ""}
          language="sql"
          className="doc-sql-editor-mirror"
        />
        <textarea
          className="doc-sql-editor-input"
          value={draft}
          ref={input}
          rows={1}
          spellCheck={false}
          placeholder={SQL_PLACEHOLDER}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
              event.preventDefault();
              run();
              return;
            }
            if (event.key === "Escape" && canCancel) {
              event.preventDefault();
              onCancel();
            }
          }}
        />
      </div>
      <div className="doc-sql-foot">
        <span>⌘↵ runs the query</span>
        <span className="flex-1" />
        {canCancel ? (
          <Button size="sm" variant="default" onClick={onCancel}>
            Cancel
          </Button>
        ) : null}
        <Button size="sm" variant="primary" disabled={!ready} onClick={run}>
          Run
        </Button>
      </div>
    </div>
  );
}

function SqlCard({
  query,
  spec,
  onEdit,
}: {
  query: string;
  spec: ChartBlockSpec;
  onEdit: () => void;
}) {
  const [showQuery, setShowQuery] = useState(false);
  const url = useEvidenceUrl("hogql", query);
  return (
    <div className="doc-sql-card">
      <div className="doc-sql-head">
        <button
          type="button"
          className="doc-sql-toggle"
          aria-expanded={showQuery}
          onClick={() => setShowQuery((open) => !open)}
        >
          {showQuery ? (
            <CaretDownIcon size={11} />
          ) : (
            <CaretRightIcon size={11} />
          )}
          <span>SQL</span>
          {showQuery ? null : (
            <HighlightedCode
              code={oneLine(query)}
              language="sql"
              className="doc-sql-peek"
            />
          )}
        </button>
        <span className="doc-sql-actions">
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  size="icon"
                  variant="default"
                  aria-label="Edit the query"
                  onClick={onEdit}
                />
              }
            >
              <PencilSimpleIcon size={13} />
            </TooltipTrigger>
            <TooltipContent>Edit the query</TooltipContent>
          </Tooltip>
          {url ? (
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    size="icon"
                    variant="default"
                    aria-label="Open in PostHog"
                    onClick={() => openExternalUrl(url)}
                  />
                }
              >
                <ArrowSquareOutIcon size={13} />
              </TooltipTrigger>
              <TooltipContent>Open in PostHog</TooltipContent>
            </Tooltip>
          ) : null}
        </span>
      </div>
      {showQuery ? (
        <HighlightedCode code={query} language="sql" className="doc-sql-full" />
      ) : null}
      <div className="doc-sql-result">
        <MessageChartCard
          spec={spec}
          blockKey={chartBlockKey(JSON.stringify(spec))}
          showStat={false}
        />
      </div>
    </div>
  );
}

export function ObjectBlockView({
  node,
  updateAttributes,
}: ReactNodeViewProps) {
  const attrs = node.attrs as ObjectBlockAttrs;
  const isSql = attrs.mode === "hogql";
  const [editing, setEditing] = useState(isSql && !attrs.query);
  const spec = toSpec(attrs);

  if (isSql && (editing || !spec)) {
    return (
      <NodeViewWrapper className="my-4">
        <SqlEditor
          initial={attrs.query ?? ""}
          canCancel={!!attrs.query}
          onRun={(query) => {
            updateAttributes({ query });
            setEditing(false);
          }}
          onCancel={() => setEditing(false)}
        />
      </NodeViewWrapper>
    );
  }

  return (
    <NodeViewWrapper
      className="my-4"
      data-drag-handle
      data-request-id={attrs.requestId || undefined}
    >
      {spec && isSql && attrs.query ? (
        <SqlCard
          query={attrs.query}
          spec={spec}
          onEdit={() => setEditing(true)}
        />
      ) : spec ? (
        <MessageChartCard
          spec={spec}
          blockKey={chartBlockKey(JSON.stringify(spec))}
          showStat={false}
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
      requestId: { default: null },
    };
  },

  parseHTML() {
    return [{ tag: "div[data-object-block]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "div",
      mergeAttributes(HTMLAttributes, {
        "data-object-block": "",
        "data-request-id": HTMLAttributes.requestId || undefined,
      }),
    ];
  },

  addNodeView() {
    return ReactNodeViewRenderer(ObjectBlockView);
  },
});
