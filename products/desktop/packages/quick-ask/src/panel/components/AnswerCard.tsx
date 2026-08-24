import { EvidenceRefChip } from "@posthog/ui/features/editor/components/EvidenceRefChip";
import {
  baseComponents,
  MarkdownRenderer,
} from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { useCopy } from "@posthog/ui/primitives/useCopy";
import {
  chartBlockKey,
  isGeneratedChartBlock,
  parseChartBlock,
} from "@posthog/ui/utils/chartBlocks";
import {
  type EvidenceLinkTarget,
  parseEvidenceLink,
} from "@posthog/ui/utils/evidenceLinks";
import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Components } from "react-markdown";
import { PanelChartCard } from "./PanelChartCard";

const AUTOSCROLL_SLACK_PX = 48;

/**
 * The shared reference chip with its live hover preview. The chip's own
 * click-out is suppressed: in the panel the hover card is the destination,
 * and its "open" affordance still links out.
 */
function PanelChip({
  target,
  children,
}: {
  target: EvidenceLinkTarget;
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <span
      className="qa-ref"
      onClickCapture={(event) => {
        event.preventDefault();
        event.stopPropagation();
      }}
    >
      <EvidenceRefChip target={target}>{children}</EvidenceRefChip>
    </span>
  );
}

const BaseAnchor = baseComponents.a as React.ComponentType<{
  href?: string;
  children?: React.ReactNode;
}>;
const BaseCode = baseComponents.code as React.ComponentType<{
  className?: string;
  children?: React.ReactNode;
}>;
/** Panel rendering for the shared tag pipeline: compact charts, plain chips. */
const panelComponents: Partial<Components> = {
  a: ({ href, children }) => {
    const target = parseEvidenceLink(href);
    if (target) {
      return <PanelChip target={target}>{children}</PanelChip>;
    }
    return <BaseAnchor href={href}>{children}</BaseAnchor>;
  },
  code: ({ className, children, node }) => {
    // The AST marker is the trust boundary: only plugin-generated blocks
    // resolve to live queries; a hand-authored fence stays a code block.
    if (isGeneratedChartBlock(node)) {
      const spec = parseChartBlock(String(children).replace(/\n$/, ""));
      if (!spec) return null;
      return (
        <PanelChartCard key={chartBlockKey(String(children))} spec={spec} />
      );
    }
    return <BaseCode className={className}>{children}</BaseCode>;
  },
  pre: (props) => {
    // A chart block renders as a card, not inside a code block shell.
    if (isGeneratedChartBlock(props.node?.children[0])) {
      return props.children;
    }
    return <pre className="qa-pre">{props.children}</pre>;
  },
};

export function ThinkingCard({ label }: { label: string }): React.JSX.Element {
  return (
    <div className="qa-card qa-card-thinking">
      <div className="qa-thinking-header">
        <span className="qa-thinking-dots" aria-hidden="true">
          <span />
          <span />
          <span />
        </span>
        {/* Keyed so a new reasoning step slides in instead of just swapping. */}
        <span key={label} className="qa-thinking-label">
          {label}
        </span>
      </div>
      <div className="qa-skeleton qa-skeleton-line-wide" />
      <div className="qa-skeleton qa-skeleton-line" />
      <div className="qa-skeleton qa-skeleton-line-short" />
    </div>
  );
}

export function ErrorCard({ message }: { message: string }): React.JSX.Element {
  return (
    <div className="qa-card">
      <div className="qa-error">{message}</div>
    </div>
  );
}

export interface AnswerPart {
  id: string;
  content: string;
  complete: boolean;
}

interface AnswerCardProps {
  /** Answer segments: text stretches separated by tool activity. */
  parts: AnswerPart[];
  /** Still receiving tokens: show the streaming caret, hold the actions. */
  streaming: boolean;
  /** Latest agent activity, shown above the answer until the turn is done. */
  statusLabel: string | null;
  onOpenInApp: () => void;
}

export function AnswerCard({
  parts,
  streaming,
  statusLabel,
  onOpenInApp,
}: AnswerCardProps): React.JSX.Element {
  // Sets `copied` only after the clipboard write resolves, so the button
  // never reports a success that didn't happen (unfocused panel, blocked
  // permission).
  const { copied, copy } = useCopy(1400);
  // null follows the newest segment; a number pins an earlier one.
  const [pinned, setPinned] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pinnedToBottom = useRef(true);

  const shownIndex =
    pinned === null
      ? Math.max(parts.length - 1, 0)
      : Math.min(pinned, parts.length - 1);
  const shown = parts[shownIndex];
  const text = shown?.content ?? "";

  const copyAnswer = useCallback((): void => {
    copy(parts.map((part) => part.content).join("\n\n"));
  }, [copy, parts]);

  const page = useCallback(
    (direction: -1 | 1): void => {
      setPinned((current) => {
        const base = current === null ? parts.length - 1 : current;
        const next = Math.min(Math.max(base + direction, 0), parts.length - 1);
        return next === parts.length - 1 ? null : next;
      });
    },
    [parts.length],
  );

  // Follow the stream, but stop if the user scrolled up to read.
  const onScroll = useCallback((): void => {
    const el = scrollRef.current;
    if (!el) return;
    pinnedToBottom.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < AUTOSCROLL_SLACK_PX;
  }, []);

  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll on every text growth
  useEffect(() => {
    const el = scrollRef.current;
    if (el && streaming && pinnedToBottom.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [text, streaming]);

  const pager =
    parts.length > 1 ? (
      <span className="qa-pager">
        <button
          type="button"
          aria-label="Previous part"
          disabled={shownIndex === 0}
          onClick={() => page(-1)}
        >
          ‹
        </button>
        {shownIndex + 1}/{parts.length}
        <button
          type="button"
          aria-label="Next part"
          disabled={shownIndex === parts.length - 1}
          onClick={() => page(1)}
        >
          ›
        </button>
      </span>
    ) : null;

  const streamingShown = streaming && shownIndex === parts.length - 1;

  return (
    <div className="qa-card">
      {/* The pager lives up here: the card is top-anchored, so paging between
          segments of different heights never moves it. */}
      {(streaming || pager) && (
        <div className="qa-status-row">
          {streaming && (
            <>
              <span className="qa-thinking-dots" aria-hidden="true">
                <span />
                <span />
                <span />
              </span>
              <span key={statusLabel} className="qa-thinking-label">
                {statusLabel || "Working…"}
              </span>
            </>
          )}
          {pager}
        </div>
      )}
      <div ref={scrollRef} className="qa-card-scroll" onScroll={onScroll}>
        <div
          key={shown?.id ?? "empty"}
          className={
            streamingShown
              ? "qa-answer qa-streaming qa-seg-in"
              : "qa-answer qa-seg-in"
          }
        >
          <MarkdownRenderer
            content={text}
            renderObjectTags
            componentsOverride={panelComponents}
          />
        </div>
      </div>

      {!streaming && (
        <div className="qa-actions">
          <button type="button" className="qa-button" onClick={copyAnswer}>
            {copied ? "Copied" : "Copy"}
          </button>
          <button
            type="button"
            className="qa-button qa-primary"
            onClick={onOpenInApp}
          >
            Open in PostHog
          </button>
        </div>
      )}
    </div>
  );
}
