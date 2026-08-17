import { EvidenceRefChip } from "@posthog/ui/features/editor/components/EvidenceRefChip";
import {
  baseComponents,
  MarkdownRenderer,
} from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { chartBlockKey, parseChartBlock } from "@posthog/ui/utils/chartBlocks";
import {
  type EvidenceLinkTarget,
  parseEvidenceLink,
} from "@posthog/ui/utils/evidenceLinks";
import type React from "react";
import {
  isValidElement,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
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
  code: ({ className, children }) => {
    if (className?.match(/language-posthog-chart/)) {
      const spec = parseChartBlock(String(children).replace(/\n$/, ""));
      if (!spec) return null;
      return (
        <PanelChartCard key={chartBlockKey(String(children))} spec={spec} />
      );
    }
    return <BaseCode className={className}>{children}</BaseCode>;
  },
  pre: ({ children }) => {
    // A chart block renders as a card, not inside a code block shell.
    if (
      isValidElement<{ className?: string }>(children) &&
      children.props.className?.includes("language-posthog-chart")
    ) {
      return children;
    }
    return <pre className="qa-pre">{children}</pre>;
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

interface AnswerCardProps {
  /** Concatenated markdown of the answer so far. */
  text: string;
  /** Still receiving tokens: show the streaming caret, hold the actions. */
  streaming: boolean;
  onOpenInApp: () => void;
}

export function AnswerCard({
  text,
  streaming,
  onOpenInApp,
}: AnswerCardProps): React.JSX.Element {
  const [copied, setCopied] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pinnedToBottom = useRef(true);

  const copyAnswer = useCallback((): void => {
    void navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1400);
  }, [text]);

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

  return (
    <div className="qa-card">
      <div ref={scrollRef} className="qa-card-scroll" onScroll={onScroll}>
        <div className={streaming ? "qa-answer qa-streaming" : "qa-answer"}>
          {/* Object tags in the markdown resolve into live chips and chart cards. */}
          <MarkdownRenderer
            content={text}
            componentsOverride={panelComponents}
          />
        </div>
      </div>

      {!streaming && (
        <div className="qa-actions">
          <span className="qa-source">PostHog AI</span>
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
